import logging
import re
from html import unescape
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Categories to scrape — covers marketing, communications, and tech/web
ISARTA_CATEGORIES = ['marketing', 'communications', 'web-ti-ia']


class IsartaScraper(BaseScraper):
    SOURCE_NAME = 'Isarta'
    BASE_URL = 'https://isarta.com'

    def build_search_url(self, keyword, location='Montreal'):
        """Not used — Isarta searches by category, not keyword."""
        return f"{self.BASE_URL}/cgi-bin/emplois/jobs?cat={keyword}"

    def scrape(self, keywords, location='Montreal'):
        """Override to search by category instead of keyword.

        Isarta organizes jobs by domain (marketing, communications, web-ti-ia).
        We scrape each category once — no need to repeat per keyword since
        all jobs in the category are returned on a single page.
        """
        all_jobs = []
        seen_ids = set()

        for category in ISARTA_CATEGORIES:
            try:
                url = f"{self.BASE_URL}/cgi-bin/emplois/jobs?cat={category}"
                logger.info(f"[Isarta] Scraping categorie: {category}")
                soup = self._get_soup(url)
                if soup is None:
                    continue

                jobs = self.parse_listing(soup)

                # Deduplicate across categories (same job can appear in multiple)
                new_jobs = []
                for job in jobs:
                    job_id = job.get('_isarta_id', '')
                    if job_id and job_id in seen_ids:
                        continue
                    if job_id:
                        seen_ids.add(job_id)
                    job['source'] = self.SOURCE_NAME
                    job['job_type'] = self.normalize_job_type(job.get('job_type', ''))
                    new_jobs.append(job)

                all_jobs.extend(new_jobs)
                logger.info(f"[Isarta] {len(new_jobs)} offres pour categorie '{category}' "
                            f"({len(jobs) - len(new_jobs)} doublons ignores)")

            except Exception as e:
                logger.error(f"[Isarta] Erreur scraping categorie '{category}': {e}")
                continue

        # Remove internal tracking key before returning
        for job in all_jobs:
            job.pop('_isarta_id', None)

        logger.info(f"[Isarta] Total: {len(all_jobs)} offres uniques")
        return all_jobs

    def parse_listing(self, soup):
        """Parse job cards from the listing page.

        Each job card is a div.well-listing-monopage with rich data-* attributes
        containing all job information including the full description.
        """
        jobs = []
        cards = soup.select('div.well-listing-monopage')

        logger.info(f"[Isarta] {len(cards)} cartes trouvees dans le HTML")

        for card in cards:
            try:
                job_id = card.get('data-login', '').strip()
                if not job_id:
                    continue

                # Title from data-poste or h2.poste-listing-monopage
                title = card.get('data-poste', '').strip()
                if not title:
                    title_el = card.select_one('h2.poste-listing-monopage')
                    if title_el:
                        title = title_el.get_text(strip=True)
                if not title:
                    continue

                # Company from data-company1 or h3.compagnie-listing-monopage
                company = card.get('data-company1', '').strip()
                if not company:
                    company_el = card.select_one('h3.compagnie-listing-monopage')
                    if company_el:
                        company = company_el.get_text(strip=True)

                # Location from data-lieu or h4.lieu-listing-monopage
                location = card.get('data-lieu', '').strip()
                if not location:
                    loc_el = card.select_one('h4.lieu-listing-monopage')
                    if loc_el:
                        location = loc_el.get_text(strip=True)

                # URL — constructed from job ID
                url = f"{self.BASE_URL}/emplois/?job={job_id}"

                # Salary from data-salaire
                salary = card.get('data-salaire', '').strip()

                # Job type from data-type (Permanent, Temporaire, etc.)
                job_type_raw = card.get('data-type', '').strip()
                # Schedule from data-horaire (Temps plein, Temps partiel)
                horaire = card.get('data-horaire', '').strip()
                # Combine type and schedule
                job_type = job_type_raw
                if horaire and horaire.lower() != job_type_raw.lower():
                    job_type = f"{job_type_raw} - {horaire}" if job_type_raw else horaire

                # Work type (teletravail/hybride/presentiel) from data-teletravail
                teletravail_raw = card.get('data-teletravail', '').strip()
                work_type = ''
                if teletravail_raw:
                    work_type = self._detect_work_type(teletravail_raw)

                # Date posted from data-register-date
                date_posted = card.get('data-register-date', '').strip()

                # Description from data-description (HTML-encoded)
                description = ''
                desc_raw = card.get('data-description', '').strip()
                if desc_raw:
                    # Double-encoded HTML entities: &amp;agrave; -> &agrave; -> à
                    desc_html = unescape(unescape(desc_raw))
                    desc_soup = BeautifulSoup(desc_html, 'lxml')
                    description = desc_soup.get_text(' ', strip=True)
                    description = re.sub(r'\s+', ' ', description)
                    description = description[:3000]

                # If work_type not found from teletravail field, try description
                if not work_type and description:
                    work_type = self._detect_work_type(description)

                # If job_type not found, try detecting from card text
                if not job_type:
                    card_text = card.get_text(' ', strip=True)
                    job_type = self.detect_job_type(card_text)

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': url,
                    'salary': salary,
                    'work_type': work_type,
                    'job_type': job_type,
                    'date_posted': date_posted,
                    'description': description,
                    '_isarta_id': job_id,
                })

            except Exception as e:
                logger.debug(f"[Isarta] Erreur parsing carte: {e}")
                continue

        return jobs

    def parse_detail(self, soup, job):
        """Extract additional info from Isarta detail page.

        Usually not needed since the listing page data-* attributes contain
        everything including the full description. This is a fallback for
        enrichment via enrich_jobs_batch.
        """
        # Description — look for the main content area
        if not job.get('description'):
            # The detail page loads via /cgi-bin/emplois/jobs?display=ID
            # Description is in the main content container
            for selector in [
                'div.container-monopage',
                '#rapide-detail-offre-monopage',
                'div[class*="description"]',
                'article',
            ]:
                desc_el = soup.select_one(selector)
                if desc_el:
                    desc = desc_el.get_text(' ', strip=True)
                    desc = re.sub(r'\s+', ' ', desc)
                    if len(desc) > 100:
                        job['description'] = desc[:3000]
                        break

        page_text = soup.get_text(' ', strip=True)
        page_text = re.sub(r'\s+', ' ', page_text)

        # Fill missing fields from detail page text
        if not job.get('salary'):
            job['salary'] = self.detect_salary(page_text)
        if not job.get('job_type'):
            job['job_type'] = self.detect_job_type(page_text)
        if not job.get('work_type'):
            job['work_type'] = self._detect_work_type(page_text)

        # Date posted
        if not job.get('date_posted'):
            date_match = re.search(
                r'Publi[ée]e?\s*[:]\s*(\d{1,2}/\d{2}/\d{4})',
                page_text, re.IGNORECASE,
            )
            if date_match:
                job['date_posted'] = date_match.group(1)

        return job
