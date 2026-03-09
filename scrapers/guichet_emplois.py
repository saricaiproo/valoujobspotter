import logging
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class GuichetEmploisScraper(BaseScraper):
    """
    Guichet-Emplois (Job Bank Canada) - Government of Canada job board.
    French-language government job site, very scraper-friendly.
    """
    SOURCE_NAME = 'Guichet-Emplois'
    BASE_URL = 'https://www.guichetemplois.gc.ca'

    def build_search_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        # sort=M = most recent, fpod=7 = posted in last 7 days
        return f"{self.BASE_URL}/jobsearch/rechercheemploi?searchstring={kw}&locationstring=Montr%C3%A9al%2C+QC&sort=M&fpod=7"

    def parse_listing(self, soup):
        jobs = []

        # Job Bank uses article elements with class 'results-card'
        cards = soup.select('article.resultJobItem, article[class*="result"], div.results-card')
        logger.info(f"[Guichet-Emplois] {len(cards)} cartes (methode 1)")

        if not cards:
            # Fallback: try noc-result items or generic job list items
            cards = soup.select('div.job-result, div[class*="job-result"], a.resultJobItem')
            logger.info(f"[Guichet-Emplois] {len(cards)} cartes (methode 2 fallback)")

        if not cards:
            # Last resort: look for any links to job postings
            all_links = soup.select('a[href*="/offredemploi/"]')
            logger.info(f"[Guichet-Emplois] {len(all_links)} liens vers offres (methode 3 fallback)")
            for link_el in all_links:
                title = link_el.get_text(strip=True)
                href = link_el.get('href', '')
                if not title or not href:
                    continue
                if not href.startswith('http'):
                    href = self.BASE_URL + href

                # Try to get parent container for more info
                parent = link_el.find_parent(['article', 'div', 'li'])
                company = ''
                location_text = ''
                salary = ''

                if parent:
                    # Look for company/employer
                    for el in parent.select('span, div, li'):
                        text = el.get_text(strip=True)
                        if not text or text == title:
                            continue
                        if '$' in text or 'heure' in text.lower() or 'annuel' in text.lower():
                            salary = text
                        elif any(loc in text.lower() for loc in ['qc', 'québec', 'quebec', 'montréal', 'montreal', 'laval']):
                            location_text = text
                        elif not company and len(text) < 80:
                            company = text

                work_type = self._detect_work_type(title + ' ' + location_text)

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location_text,
                    'url': href,
                    'salary': salary,
                    'work_type': work_type,
                    'description': '',
                })
            return jobs

        for card in cards:
            try:
                # Title - usually in a link to the job posting
                title_el = card.select_one('a[href*="/offredemploi/"], h3 a, h2 a, a.resultJobItem')
                if not title_el:
                    title_el = card.select_one('a')
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if not title:
                    continue

                link = title_el.get('href', '')
                if link and not link.startswith('http'):
                    link = self.BASE_URL + link
                if not link:
                    continue

                # Company
                company = ''
                company_el = card.select_one('span.business, div.business, li.business, span[class*="employer"], span[class*="company"]')
                if company_el:
                    company = company_el.get_text(strip=True)
                if not company:
                    # Try second element that looks like company
                    spans = card.select('span, li')
                    for s in spans:
                        text = s.get_text(strip=True)
                        if text and text != title and '$' not in text and len(text) < 80:
                            if not any(loc in text.lower() for loc in ['qc', 'montréal', 'montreal']):
                                company = text
                                break

                # Location
                location_text = ''
                loc_el = card.select_one('span.location, div.location, li.location, span[class*="location"]')
                if loc_el:
                    location_text = loc_el.get_text(strip=True)

                # Salary
                salary = ''
                sal_el = card.select_one('span.salary, div.salary, li.salary, span[class*="salary"]')
                if sal_el:
                    salary = sal_el.get_text(strip=True)

                work_type = self._detect_work_type(title + ' ' + location_text)

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location_text,
                    'url': link,
                    'salary': salary,
                    'work_type': work_type,
                    'description': '',
                })
            except Exception as e:
                logger.debug(f"[Guichet-Emplois] Erreur parsing carte: {e}")
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
