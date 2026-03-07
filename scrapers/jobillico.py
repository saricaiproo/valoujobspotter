import logging
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class JobillicoScraper(BaseScraper):
    SOURCE_NAME = 'Jobillico'
    BASE_URL = 'https://www.jobillico.com'

    def build_search_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        loc = quote_plus(location)
        return f"{self.BASE_URL}/recherche-emploi?skwd={kw}&sloc={loc}"

    def parse_listing(self, soup):
        jobs = []
        cards = soup.select('div.job-item, div.search-results-job-item, article.job-card')

        for card in cards:
            try:
                title_el = card.select_one('a.job-title, h2 a, a.title, a[data-job-title]')
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get('href', '')
                if link and not link.startswith('http'):
                    link = self.BASE_URL + link
                if not link:
                    continue

                company_el = card.select_one('span.company-name, a.company-name, div.company')
                company = company_el.get_text(strip=True) if company_el else ''

                location_el = card.select_one('span.location, div.location, span.job-location')
                location = location_el.get_text(strip=True) if location_el else ''

                salary_el = card.select_one('span.salary, div.salary')
                salary = salary_el.get_text(strip=True) if salary_el else ''

                desc_el = card.select_one('div.description, p.description, div.job-description')
                description = desc_el.get_text(strip=True) if desc_el else ''

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
                logger.debug(f"[Jobillico] Erreur parsing carte: {e}")
                continue

        return jobs

    def _detect_work_type(self, text):
        text_lower = text.lower()
        if 'télétravail' in text_lower or 'remote' in text_lower or 'teletravail' in text_lower:
            return 'teletravail'
        elif 'hybride' in text_lower or 'hybrid' in text_lower:
            return 'hybride'
        elif 'présentiel' in text_lower or 'sur place' in text_lower:
            return 'presentiel'
        return ''
