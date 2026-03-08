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
        cards = soup.select('article.card')

        logger.info(f"[Jobillico] {len(cards)} cartes trouvees dans le HTML")

        for card in cards:
            try:
                title_el = card.select_one('h4.card__content__section__title a, h4.card__content__section__title, a.gtm_searchEngine-featuredJob')
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if not title:
                    continue

                # Get link
                link = ''
                link_el = card.select_one('a[href]')
                if link_el:
                    link = link_el.get('href', '')
                if title_el.name == 'a':
                    link = title_el.get('href', '')

                if link and not link.startswith('http'):
                    link = self.BASE_URL + link
                if not link:
                    continue

                # Company from card header or content
                company_el = card.select_one('div.card__header a, div.card__header span, div.card__content a')
                company = ''
                if company_el:
                    company = company_el.get_text(strip=True)
                    # Don't use the job title as company name
                    if company == title:
                        company = ''

                # Location from list items
                location = ''
                location_items = card.select('li.list__item')
                for li in location_items:
                    text = li.get_text(strip=True)
                    if any(loc in text.lower() for loc in ['montréal', 'montreal', 'laval', 'longueuil', 'québec', 'quebec', 'brossard']):
                        location = text
                        break

                # Salary
                salary = ''
                salary_el = card.select_one('li.list__item--salary')
                if salary_el:
                    salary = salary_el.get_text(strip=True)

                work_type = self._detect_work_type(title + ' ' + location)

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': link,
                    'salary': salary,
                    'work_type': work_type,
                    'description': '',
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
