import json
import logging
import re
import random
from urllib.parse import quote_plus, urlencode
from scrapers.base import BaseScraper, USER_AGENTS

logger = logging.getLogger(__name__)

# Try httpx (HTTP/2, least likely to be blocked), then cloudscraper, then requests
_httpx_client = None
HAS_HTTPX = False
HAS_CLOUDSCRAPER = False

try:
    import httpx
    _httpx_client = httpx.Client(http2=True, follow_redirects=True, timeout=30)
    HAS_HTTPX = True
    logger.info("[Indeed] httpx (HTTP/2) disponible")
except ImportError:
    pass

try:
    import cloudscraper
    _cloudscraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )
    HAS_CLOUDSCRAPER = True
    logger.info("[Indeed] cloudscraper disponible")
except ImportError:
    pass

if not HAS_HTTPX and not HAS_CLOUDSCRAPER:
    import requests
    _fallback = requests.Session()
    logger.info("[Indeed] fallback sur requests")


class IndeedScraper(BaseScraper):
    SOURCE_NAME = 'Indeed'
    BASE_URL = 'https://ca.indeed.com'

    def build_search_url(self, keyword, location='Montreal', start=0):
        params = {
            'q': keyword,
            'l': location,
            'sort': 'date',
            'fromage': 7,  # Last 7 days
            'filter': 0,
            'start': start,
        }
        return f"{self.BASE_URL}/jobs?{urlencode(params)}"

    def _build_rss_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        loc = quote_plus(location)
        return f"{self.BASE_URL}/rss?q={kw}&l={loc}&sort=date&fromage=7"

    def _get(self, url):
        """Make a GET request: try httpx (HTTP/2) → cloudscraper → requests."""
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'fr-CA,fr;q=0.9,en-CA;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        }
        self._delay()

        # Try httpx (HTTP/2) first — least likely to be blocked
        if HAS_HTTPX:
            try:
                response = _httpx_client.get(url, headers=headers)
                if response.status_code == 200:
                    return response
                logger.debug(f"[Indeed] httpx status {response.status_code}, trying cloudscraper")
            except Exception as e:
                logger.debug(f"[Indeed] httpx failed: {e}")

        # Try cloudscraper (handles Cloudflare JS challenges)
        if HAS_CLOUDSCRAPER:
            try:
                response = _cloudscraper.get(url, headers=headers, timeout=30)
                return response
            except Exception as e:
                logger.debug(f"[Indeed] cloudscraper failed: {e}")

        # Last resort: plain requests
        return _fallback.get(url, headers=headers, timeout=30)

    def scrape(self, keywords, location='Montreal'):
        all_jobs = []
        for keyword in keywords:
            jobs = self._scrape_html(keyword, location)
            if not jobs:
                # Fallback to RSS if HTML scraping fails
                jobs = self._scrape_rss(keyword, location)
            all_jobs.extend(jobs)
        return all_jobs

    def _scrape_html(self, keyword, location):
        """Try to scrape Indeed via HTML with embedded JSON extraction."""
        jobs = []
        for page in range(1):  # 1 page per keyword
            start = page * 10
            try:
                url = self.build_search_url(keyword, location, start=start)
                logger.info(f"[Indeed] HTML recherche: {keyword} @ {location} (start={start})")
                response = self._get(url)

                if response.status_code == 403:
                    logger.warning(f"[Indeed] Bloqué (403) - Cloudflare. Essai RSS...")
                    return []
                if response.status_code != 200:
                    logger.warning(f"[Indeed] Status {response.status_code}")
                    break

                html = response.text
                page_jobs = self._extract_json_jobs(html)

                if not page_jobs:
                    # Fallback to HTML parsing
                    page_jobs = self._parse_html_jobs(html)

                if not page_jobs:
                    logger.info(f"[Indeed] Aucun résultat page {page + 1}")
                    break

                for job in page_jobs:
                    job['source'] = self.SOURCE_NAME
                    job['job_type'] = self.normalize_job_type(job.get('job_type', ''))
                jobs.extend(page_jobs)
                logger.info(f"[Indeed] {len(page_jobs)} offres page {page + 1} pour '{keyword}'")

                if len(page_jobs) < 5:
                    break

            except Exception as e:
                logger.error(f"[Indeed] Erreur HTML '{keyword}' page {page + 1}: {e}")
                break

        return jobs

    def _extract_json_jobs(self, html):
        """Extract jobs from Indeed's embedded JSON data."""
        jobs = []

        # Look for the mosaic provider data
        pattern = r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.+?\});'
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            return []

        try:
            data = json.loads(match.group(1))
            results = (data.get('metaData', {})
                       .get('mosaicProviderJobCardsModel', {})
                       .get('results', []))

            for item in results:
                try:
                    title = item.get('title', '').strip()
                    if not title:
                        continue

                    jobkey = item.get('jobkey', '')
                    company = item.get('company', '').strip()
                    location = item.get('companyLocation', '').strip()
                    snippet = item.get('snippet', '') or ''
                    # Clean HTML from snippet
                    snippet = re.sub(r'<[^>]+>', ' ', snippet)
                    snippet = re.sub(r'\s+', ' ', snippet).strip()

                    salary = ''
                    sal_snippet = item.get('salarySnippet', {})
                    if sal_snippet:
                        salary = sal_snippet.get('text', '')
                    if not salary:
                        estimated = item.get('estimatedSalary', {})
                        if estimated:
                            sal_min = estimated.get('min', '')
                            sal_max = estimated.get('max', '')
                            sal_type = estimated.get('type', '')
                            if sal_min and sal_max:
                                salary = f"{sal_min}$ - {sal_max}$ / {sal_type}"

                    date_posted = item.get('pubDate', '')
                    if not date_posted:
                        # formattedRelativeTime is like "il y a 3 jours"
                        date_posted = item.get('formattedRelativeTime', '')

                    link = f"https://ca.indeed.com/viewjob?jk={jobkey}" if jobkey else ''

                    full_text = f"{title} {snippet} {location}"
                    work_type = self._detect_work_type(full_text)
                    job_type = self.detect_job_type(full_text)

                    jobs.append({
                        'title': title,
                        'company': company,
                        'location': location,
                        'url': link,
                        'salary': salary,
                        'work_type': work_type,
                        'job_type': job_type,
                        'date_posted': date_posted,
                        'description': snippet[:3000],
                    })
                except Exception as e:
                    logger.debug(f"[Indeed] Erreur parsing JSON item: {e}")
                    continue

        except (json.JSONDecodeError, KeyError) as e:
            logger.debug(f"[Indeed] Erreur décodage JSON: {e}")

        return jobs

    def _parse_html_jobs(self, html):
        """Fallback: parse Indeed HTML with BeautifulSoup."""
        from bs4 import BeautifulSoup
        jobs = []
        soup = BeautifulSoup(html, 'lxml')

        # Look for job cards
        cards = soup.select('div.job_seen_beacon, li.css-5lfssm')
        if not cards:
            # Try broader selector
            cards = soup.select('[data-jk]')

        for card in cards:
            try:
                # Title
                title_el = card.select_one('h2.jobTitle a span, h2 a span, a.jcs-JobTitle span')
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)

                # Link
                link_el = card.select_one('a.jcs-JobTitle, h2 a[href]')
                link = ''
                if link_el:
                    href = link_el.get('href', '')
                    if href:
                        jk_match = re.search(r'jk=([a-f0-9]+)', href)
                        if jk_match:
                            link = f"https://ca.indeed.com/viewjob?jk={jk_match.group(1)}"
                        elif href.startswith('http'):
                            link = href
                        else:
                            link = self.BASE_URL + href

                if not link:
                    jk = card.get('data-jk', '')
                    if jk:
                        link = f"https://ca.indeed.com/viewjob?jk={jk}"

                if not link:
                    continue

                # Company
                company_el = card.select_one('span[data-testid="company-name"], span.companyName')
                company = company_el.get_text(strip=True) if company_el else ''

                # Location
                loc_el = card.select_one('div[data-testid="text-location"], div.companyLocation')
                location = loc_el.get_text(strip=True) if loc_el else ''

                # Salary
                salary_el = card.select_one('div.salary-snippet-container, div.metadata.salary-snippet-container')
                salary = salary_el.get_text(strip=True) if salary_el else ''

                # Date
                date_el = card.select_one('span.date, span[data-testid="myJobsStateDate"]')
                date_posted = date_el.get_text(strip=True) if date_el else ''

                # Snippet
                snippet_el = card.select_one('div.job-snippet, td.snip')
                snippet = snippet_el.get_text(' ', strip=True) if snippet_el else ''

                full_text = f"{title} {snippet} {location}"
                work_type = self._detect_work_type(full_text)

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': link,
                    'salary': salary,
                    'work_type': work_type,
                    'date_posted': date_posted,
                    'description': snippet[:3000],
                })
            except Exception as e:
                logger.debug(f"[Indeed] Erreur parsing HTML card: {e}")
                continue

        return jobs

    def _scrape_rss(self, keyword, location):
        """Fallback: try RSS feed."""
        jobs = []
        try:
            url = self._build_rss_url(keyword, location)
            logger.info(f"[Indeed] RSS fallback: {keyword} @ {location}")
            response = self._get(url)

            if response.status_code != 200:
                logger.warning(f"[Indeed] RSS status {response.status_code}")
                return []

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'lxml-xml')
            items = soup.find_all('item')

            for item in items:
                try:
                    title_el = item.find('title')
                    link_el = item.find('link')
                    if not title_el:
                        continue

                    title = title_el.get_text(strip=True)
                    link = ''
                    if link_el:
                        link = link_el.get_text(strip=True)
                        if not link:
                            link = link_el.next_sibling
                            if link:
                                link = str(link).strip()

                    if not link or not link.startswith('http'):
                        continue

                    source_el = item.find('source')
                    company = source_el.get_text(strip=True) if source_el else ''

                    desc_el = item.find('description')
                    description = ''
                    if desc_el:
                        description = desc_el.get_text(strip=True)
                        description = re.sub(r'<[^>]+>', ' ', description)
                        description = re.sub(r'\s+', ' ', description).strip()

                    pub_date = ''
                    date_el = item.find('pubdate') or item.find('pubDate')
                    if date_el:
                        pub_date = date_el.get_text(strip=True)

                    full_text = f"{title} {description}"
                    work_type = self._detect_work_type(full_text)

                    jobs.append({
                        'title': title,
                        'company': company,
                        'location': self._extract_location(description),
                        'url': link,
                        'salary': self.detect_salary(full_text),
                        'work_type': work_type,
                        'date_posted': pub_date,
                        'description': description[:3000],
                        'source': self.SOURCE_NAME,
                    })
                except Exception as e:
                    logger.debug(f"[Indeed] Erreur parsing RSS item: {e}")
                    continue

            logger.info(f"[Indeed] RSS: {len(jobs)} offres pour '{keyword}'")
        except Exception as e:
            logger.error(f"[Indeed] Erreur RSS '{keyword}': {e}")

        return jobs

    def _extract_location(self, text):
        text_lower = text.lower()
        if 'montreal' in text_lower or 'montréal' in text_lower:
            return 'Montréal, QC'
        if 'laval' in text_lower:
            return 'Laval, QC'
        if 'longueuil' in text_lower:
            return 'Longueuil, QC'
        if 'québec' in text_lower or 'quebec' in text_lower:
            return 'Québec, QC'
        return ''

    def parse_listing(self, soup):
        # Not used — scrape() handles everything
        return []
