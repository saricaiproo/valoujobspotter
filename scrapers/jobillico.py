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

        for i, card in enumerate(cards):
            try:
                # Try multiple ways to find the title
                title_el = card.select_one('h4.card__content__section__title a')
                if not title_el:
                    title_el = card.select_one('h4.card__content__section__title')
                if not title_el:
                    title_el = card.select_one('a.gtm_searchEngine-featuredJob')
                if not title_el:
                    # Last resort: any heading with a link
                    title_el = card.select_one('h3 a, h4 a, h5 a')

                if not title_el:
                    logger.debug(f"[Jobillico] Carte {i}: pas de titre trouve")
                    continue

                title = title_el.get_text(strip=True)
                if not title:
                    continue

                # Get link - try multiple approaches
                link = ''
                if title_el.name == 'a':
                    link = title_el.get('href', '')
                if not link:
                    link_el = card.select_one('a.gtm_searchEngine-featuredJob, a[href*="/offre-emploi"], a[href*="/emploi"]')
                    if link_el:
                        link = link_el.get('href', '')
                if not link:
                    link_el = card.select_one('a[href]')
                    if link_el:
                        link = link_el.get('href', '')

                if link and not link.startswith('http'):
                    link = self.BASE_URL + link
                if not link:
                    logger.debug(f"[Jobillico] Carte {i}: pas de lien pour '{title}'")
                    continue

                # Company - try card header image alt, or nearby text
                company = ''
                img_el = card.select_one('div.card__header img, img.card__header__media')
                if img_el:
                    company = img_el.get('alt', '').strip()

                if not company:
                    company_el = card.select_one('div.card__header a, div.card__content a')
                    if company_el:
                        company = company_el.get_text(strip=True)
                        if company == title:
                            company = ''

                # Location - get all list items, take first that looks like a place
                location = ''
                list_items = card.select('li.list__item')
                for li in list_items:
                    text = li.get_text(strip=True)
                    # Skip salary items and empty items
                    if 'salary' in ' '.join(li.get('class', [])):
                        continue
                    if text and '$' not in text and len(text) < 100:
                        location = text
                        break

                # Salary
                salary = ''
                salary_items = card.select('li.list__item--salary')
                for s in salary_items:
                    sal_text = s.get_text(strip=True)
                    if sal_text:
                        salary = sal_text
                        break

                work_type = self._detect_work_type(title + ' ' + location + ' ' + salary)

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
                logger.debug(f"[Jobillico] Erreur parsing carte {i}: {e}")
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
