import logging
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class JobboomScraper(BaseScraper):
    SOURCE_NAME = 'Jobboom'
    BASE_URL = 'https://www.jobboom.com'

    def build_search_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        # Try multiple URL patterns since Jobboom changes their structure
        return f"{self.BASE_URL}/fr/recherche?keywords={kw}&location=Montreal%2C+QC"

    def parse_listing(self, soup):
        jobs = []
        # Try multiple possible selectors
        cards = soup.select('div.job-card, article.job-item, div.offer-item, div.search-result-item, div.card, article.card, li.result')

        logger.info(f"[Jobboom] {len(cards)} cartes trouvees dans le HTML")

        if not cards:
            # Log what we do find to help debug
            all_articles = soup.find_all('article')
            all_divs_with_class = soup.find_all('div', class_=True)
            logger.info(f"[Jobboom] Articles: {len(all_articles)}, Divs avec classe: {len(all_divs_with_class)}")
            # Try to find any links that look like job postings
            for a_tag in soup.find_all('a', href=True):
                href = a_tag.get('href', '')
                if '/offre-emploi/' in href or '/emploi/' in href or '/job/' in href:
                    title = a_tag.get_text(strip=True)
                    if title and len(title) > 5:
                        link = href if href.startswith('http') else self.BASE_URL + href
                        jobs.append({
                            'title': title,
                            'company': '',
                            'location': 'Montreal',
                            'url': link,
                            'salary': '',
                            'work_type': '',
                            'description': '',
                        })

        for card in cards:
            try:
                title_el = card.select_one('a[href], h2 a, h3 a, h4 a')
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get('href', '')
                if link and not link.startswith('http'):
                    link = self.BASE_URL + link
                if not link or not title:
                    continue

                company_el = card.select_one('span.company, div.company-name, a.company, p.company')
                company = company_el.get_text(strip=True) if company_el else ''

                location_el = card.select_one('span.location, div.location, span.city, p.location')
                location = location_el.get_text(strip=True) if location_el else ''

                salary_el = card.select_one('span.salary, div.salary-range, p.salary')
                salary = salary_el.get_text(strip=True) if salary_el else ''

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
                logger.debug(f"[Jobboom] Erreur parsing carte: {e}")
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
