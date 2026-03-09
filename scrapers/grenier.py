import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, extract_highlights

logger = logging.getLogger(__name__)

# Sitemap XML namespace
NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}


class GrenierScraper(BaseScraper):
    SOURCE_NAME = 'Grenier'
    BASE_URL = 'https://www.grenier.qc.ca'
    SITEMAP_URL = BASE_URL + '/sitemap-jobs.xml'

    # Only fetch jobs from the last 14 days (by datePosted in JSON-LD)
    MAX_AGE_DAYS = 14
    # Cap page fetches to avoid timeouts
    MAX_PAGES = 30
    # Parallel workers for fetching individual job pages
    WORKERS = 5

    def scrape(self, keywords, location='Montreal'):
        """
        1. Fetch sitemap XML to get all job URLs
        2. Take the most recent N URLs (highest IDs = newest)
        3. Fetch pages in parallel, parse JSON-LD
        4. Filter by keyword relevance
        """
        logger.info(f"[{self.SOURCE_NAME}] Demarrage - mots-cles: {keywords}, lieu: {location}")

        # --- Step 1: Fetch sitemap and extract job URLs ---
        job_urls = self._fetch_sitemap_urls()
        if not job_urls:
            logger.error(f"[{self.SOURCE_NAME}] Aucune URL trouvee dans le sitemap")
            return []

        logger.info(f"[{self.SOURCE_NAME}] {len(job_urls)} URLs d'emplois dans le sitemap")

        # Take only the first MAX_PAGES URLs (highest IDs = most recent, sitemap is ordered desc)
        urls_to_fetch = job_urls[:self.MAX_PAGES]
        logger.info(f"[{self.SOURCE_NAME}] Recuperation de {len(urls_to_fetch)} pages max")

        # --- Step 2: Fetch pages in parallel and parse JSON-LD ---
        all_jobs = self._fetch_and_parse_jobs(urls_to_fetch)
        logger.info(f"[{self.SOURCE_NAME}] {len(all_jobs)} offres parsees avec succes")

        # --- Step 3: Filter by recency (datePosted within last 14 days) ---
        cutoff = datetime.now() - timedelta(days=self.MAX_AGE_DAYS)
        recent_jobs = []
        for job in all_jobs:
            date_str = job.get('date_posted', '')
            if date_str:
                try:
                    posted = datetime.strptime(date_str, '%Y-%m-%d')
                    if posted < cutoff:
                        continue
                except ValueError:
                    pass  # keep jobs with unparseable dates
            recent_jobs.append(job)

        logger.info(f"[{self.SOURCE_NAME}] {len(recent_jobs)} offres recentes (< {self.MAX_AGE_DAYS} jours)")

        # --- Step 4: Filter by keyword relevance ---
        filtered = self._filter_by_keywords(recent_jobs, keywords, location)
        logger.info(f"[{self.SOURCE_NAME}] {len(filtered)} offres apres filtrage par mots-cles")

        return filtered

    def _fetch_sitemap_urls(self):
        """Fetch the sitemap XML and return a list of job page URLs."""
        try:
            logger.info(f"[{self.SOURCE_NAME}] GET {self.SITEMAP_URL}")
            response = self.session.get(self.SITEMAP_URL, timeout=30)
            response.raise_for_status()

            root = ElementTree.fromstring(response.content)
            urls = []
            for url_el in root.findall('sm:url', NS):
                loc_el = url_el.find('sm:loc', NS)
                if loc_el is not None and loc_el.text:
                    loc = loc_el.text.strip()
                    # Only keep actual job pages (with numeric ID), skip search/filter pages
                    if '/emplois/' in loc and re.search(r'/emplois/\d+/', loc):
                        urls.append(loc)
            return urls

        except Exception as e:
            logger.error(f"[{self.SOURCE_NAME}] Erreur sitemap: {e}")
            return []

    def _fetch_and_parse_jobs(self, urls):
        """Fetch multiple job pages in parallel and parse JSON-LD from each."""
        jobs = []
        url_to_html = {}

        with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            futures = {pool.submit(self._fetch_detail_html, url): url for url in urls}
            for future in as_completed(futures):
                url, html = future.result()
                if html:
                    url_to_html[url] = html

        logger.info(f"[{self.SOURCE_NAME}] {len(url_to_html)}/{len(urls)} pages recuperees")

        for url in urls:
            html = url_to_html.get(url)
            if not html:
                continue
            try:
                job = self._parse_job_page(url, html)
                if job:
                    jobs.append(job)
            except Exception as e:
                logger.debug(f"[{self.SOURCE_NAME}] Erreur parsing {url}: {e}")

        return jobs

    def _parse_job_page(self, url, html):
        """Parse a single job page HTML. Extract JSON-LD and fall back to HTML."""
        soup = BeautifulSoup(html, 'lxml')

        # --- Extract JSON-LD ---
        json_ld = None
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'JobPosting':
                    json_ld = data
                    break
                # Sometimes it's a list
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'JobPosting':
                            json_ld = item
                            break
            except (json.JSONDecodeError, TypeError):
                continue

        if not json_ld:
            logger.debug(f"[{self.SOURCE_NAME}] Pas de JSON-LD JobPosting: {url}")
            return None

        # --- Parse fields from JSON-LD ---
        title = json_ld.get('title', '')
        date_posted = json_ld.get('datePosted', '')

        # Company
        company = ''
        hiring_org = json_ld.get('hiringOrganization')
        if isinstance(hiring_org, dict):
            company = hiring_org.get('name', '')

        # Location
        location = ''
        job_loc = json_ld.get('jobLocation')
        if isinstance(job_loc, dict):
            address = job_loc.get('address', {})
            if isinstance(address, dict):
                city = address.get('addressLocality', '')
                region = address.get('addressRegion', '')
                if city and region:
                    location = f"{city}, {region}"
                elif city:
                    location = city

        # Employment type from JSON-LD
        employment_type_raw = json_ld.get('employmentType', '')
        job_type = self._map_employment_type(employment_type_raw)

        # Description from JSON-LD (contains HTML)
        description_html = json_ld.get('description', '')
        description = ''
        if description_html:
            desc_soup = BeautifulSoup(description_html, 'lxml')
            description = desc_soup.get_text(' ', strip=True)
            description = re.sub(r'\s+', ' ', description)

        # If JSON-LD description is short, try to get more from the page HTML
        if len(description) < 200:
            page_desc = self._extract_html_description(soup)
            if page_desc and len(page_desc) > len(description):
                description = page_desc

        # Cap description length
        description = description[:3000]

        # Salary from JSON-LD
        salary = ''
        base_salary = json_ld.get('baseSalary')
        if isinstance(base_salary, dict):
            value = base_salary.get('value', {})
            if isinstance(value, dict):
                min_val = value.get('minValue', '')
                max_val = value.get('maxValue', '')
                if min_val and max_val:
                    salary = f"{min_val}$ - {max_val}$"
                elif min_val:
                    salary = f"{min_val}$"
            elif base_salary.get('value'):
                salary = str(base_salary['value'])

        # Combine all text for detection
        full_text = f"{title} {description}"

        # Detect work type (teletravail/hybride/presentiel) from description text
        work_type = self._detect_work_type(full_text)

        # Override job_type from description if JSON-LD was generic FULL_TIME
        # (some listings say FULL_TIME in JSON-LD but are actually contracts)
        detected_type = self.detect_job_type(full_text)
        if detected_type and detected_type != 'Temps plein':
            job_type = detected_type

        # Detect salary from text if not in JSON-LD
        if not salary:
            salary = self.detect_salary(full_text)

        # Highlights
        highlights = extract_highlights(full_text)

        job = {
            'title': title,
            'company': company,
            'location': location,
            'url': url,
            'salary': salary,
            'work_type': work_type,
            'job_type': job_type,
            'date_posted': date_posted,
            'description': description,
            'source': self.SOURCE_NAME,
            'highlights': highlights,
        }

        logger.info(
            f"  + {title[:45]} | {company[:20]} | "
            f"mode={work_type or '?'} type={job_type or '?'} "
            f"sal={'oui' if salary else 'non'}"
        )

        return job

    @staticmethod
    def _map_employment_type(emp_type):
        """Map schema.org employmentType to our standard French labels."""
        if not emp_type:
            return ''
        mapping = {
            'FULL_TIME': 'Temps plein',
            'PART_TIME': 'Temps partiel',
            'CONTRACTOR': 'Contrat',
            'TEMPORARY': 'Contrat',
            'INTERN': 'Stage',
            'VOLUNTEER': 'Bénévole',
            'PER_DIEM': 'Temps partiel',
            'OTHER': '',
        }
        return mapping.get(emp_type.upper(), emp_type)

    @staticmethod
    def _extract_html_description(soup):
        """Try to extract job description from the page HTML when JSON-LD is short."""
        selectors = [
            'div.job-description',
            'div.description',
            'div[class*="description"]',
            'section.description',
            'article.job-content',
            'div.content-job',
            'div.offer-description',
            'main article',
            'main .content',
        ]
        for selector in selectors:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(' ', strip=True)
                text = re.sub(r'\s+', ' ', text)
                if len(text) > 100:
                    return text
        return ''

    @staticmethod
    def _normalize_accents(text):
        """Strip French accents and unicode middle-dots for flexible matching."""
        replacements = {
            'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
            'à': 'a', 'â': 'a', 'ä': 'a',
            'ù': 'u', 'û': 'u', 'ü': 'u',
            'ô': 'o', 'ö': 'o',
            'î': 'i', 'ï': 'i',
            'ç': 'c',
            '·': '',   # middle-dot (e.g. "Chargé·e" -> "Chargée" after accent strip -> "Chargee")
            '\u00b7': '',  # middle-dot alternate
            '\u2027': '',  # hyphenation point
        }
        for char, repl in replacements.items():
            text = text.replace(char, repl)
        return text

    def _filter_by_keywords(self, jobs, keywords, location):
        """Filter jobs by keyword relevance. Keep a job if any keyword matches
        its title, company, description, or location."""
        if not keywords:
            return jobs

        # Normalize keywords for matching (full phrase patterns)
        kw_patterns = []
        for kw in keywords:
            # Escape special regex chars but allow basic matching
            pattern = re.escape(self._normalize_accents(kw.lower()))
            # Allow flexible whitespace/hyphen between words
            pattern = pattern.replace(r'\ ', r'[\s\-]+')
            kw_patterns.append(re.compile(pattern, re.IGNORECASE))

        # Build individual word patterns as fallback (words longer than 3 chars)
        kw_word_patterns = []
        for kw in keywords:
            words = self._normalize_accents(kw.lower()).split()
            for word in words:
                if len(word) > 3:
                    word_pat = re.compile(re.escape(word), re.IGNORECASE)
                    kw_word_patterns.append(word_pat)

        # Also filter by location if specified — normalize accents for comparison
        loc_lower = self._normalize_accents(location.lower()) if location else ''

        filtered = []
        for job in jobs:
            searchable = ' '.join(filter(None, [
                job.get('title', ''),
                job.get('company', ''),
                job.get('description', ''),
                job.get('location', ''),
            ])).lower()
            # Strip middle-dots and accents for matching
            searchable = self._normalize_accents(searchable)

            # Check keyword match: full phrase first, then individual words as fallback
            keyword_match = any(p.search(searchable) for p in kw_patterns)
            if not keyword_match:
                keyword_match = any(p.search(searchable) for p in kw_word_patterns)
            if not keyword_match:
                continue

            # Check location match (if specified, the job location should
            # contain the target or be empty — empty means we keep it)
            if loc_lower:
                job_loc = self._normalize_accents(job.get('location', '').lower())
                # Keep if no location specified on job or if it matches
                if job_loc and loc_lower not in job_loc and job_loc not in loc_lower:
                    # Also check province-level match for Quebec jobs
                    if 'qc' not in job_loc and 'quebec' not in job_loc:
                        continue

            filtered.append(job)

        return filtered
