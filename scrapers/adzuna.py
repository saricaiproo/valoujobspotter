import logging
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class AdzunaScraper(BaseScraper):
    """
    Adzuna free job search - scrapes public search results.
    More scraper-friendly than Indeed/LinkedIn.
    """
    SOURCE_NAME = 'Adzuna'
    BASE_URL = 'https://www.adzuna.ca'

    def build_search_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        return f"{self.BASE_URL}/search?q={kw}&loc=Quebec&loc1=Montreal"

    def parse_listing(self, soup):
        jobs = []
        cards = soup.select('div.result, article.result, div[data-aid]')

        for card in cards:
            try:
                title_el = card.select_one('h2 a, a.result__title, h2.result__title a')
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get('href', '')
                if link and not link.startswith('http'):
                    link = self.BASE_URL + link
                if not link:
                    continue

                company_el = card.select_one('div.result__company, span.result__company, a[data-company]')
                company = company_el.get_text(strip=True) if company_el else ''

                location_el = card.select_one('span.result__location, div.result__location')
                location = location_el.get_text(strip=True) if location_el else ''

                salary_el = card.select_one('span.result__salary, div.result__salary')
                salary = salary_el.get_text(strip=True) if salary_el else ''

                desc_el = card.select_one('p.result__snippet, span.result__snippet, div.result__snippet')
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
                logger.debug(f"[Adzuna] Erreur parsing carte: {e}")
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
