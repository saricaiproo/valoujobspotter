import logging
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class IndeedScraper(BaseScraper):
    SOURCE_NAME = 'Indeed'
    BASE_URL = 'https://ca.indeed.com'

    def build_search_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        loc = quote_plus(location)
        return f"{self.BASE_URL}/jobs?q={kw}&l={loc}&lang=fr&sort=date"

    def parse_listing(self, soup):
        jobs = []
        cards = soup.select('div.job_seen_beacon, div.jobsearch-ResultsList > div, div.resultContent')

        for card in cards:
            try:
                title_el = card.select_one('h2.jobTitle a, h2.jobTitle span, a.jcs-JobTitle')
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get('href', '') if title_el.name == 'a' else ''
                if title_el.name != 'a':
                    parent_a = title_el.find_parent('a')
                    if parent_a:
                        link = parent_a.get('href', '')

                if link and not link.startswith('http'):
                    link = self.BASE_URL + link

                if not link:
                    continue

                company_el = card.select_one('span.companyName, span[data-testid="company-name"], div.company_location span.companyName')
                company = company_el.get_text(strip=True) if company_el else ''

                location_el = card.select_one('div.companyLocation, div[data-testid="text-location"]')
                location = location_el.get_text(strip=True) if location_el else ''

                salary_el = card.select_one('div.salary-snippet-container, div.metadata.salary-snippet-container, span.estimated-salary')
                salary = salary_el.get_text(strip=True) if salary_el else ''

                snippet_el = card.select_one('div.job-snippet, table.jobCardShelfContainer td.resultContent')
                description = snippet_el.get_text(strip=True) if snippet_el else ''

                work_type = self._detect_work_type(title + ' ' + description + ' ' + location)

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': link,
                    'salary': salary,
                    'work_type': work_type,
                    'description': description[:500],
                })
            except Exception as e:
                logger.debug(f"[Indeed] Erreur parsing carte: {e}")
                continue

        return jobs

    def _detect_work_type(self, text):
        text_lower = text.lower()
        if 'télétravail' in text_lower or 'remote' in text_lower or 'teletravail' in text_lower:
            return 'teletravail'
        elif 'hybride' in text_lower or 'hybrid' in text_lower:
            return 'hybride'
        elif 'présentiel' in text_lower or 'sur place' in text_lower or 'on-site' in text_lower:
            return 'presentiel'
        return ''
