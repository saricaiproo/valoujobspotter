import logging
import re
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class GuichetEmploisScraper(BaseScraper):
    """
    Guichet-Emplois (Job Bank Canada) - Government of Canada job board.
    French-language government job site.
    """
    SOURCE_NAME = 'Guichet-Emplois'
    BASE_URL = 'https://www.guichetemplois.gc.ca'

    def build_search_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        # sort=M = most recent, fpod=7 = posted in last 7 days
        return f"{self.BASE_URL}/jobsearch/rechercheemplois?searchstring={kw}&locationstring=Montr%C3%A9al%2C+QC&sort=M&fpod=7"

    def parse_listing(self, soup):
        jobs = []

        # Job Bank uses <a class="jobposting"> links to /jobsearch/jobposting/ID
        cards = soup.select('a[href*="/jobsearch/jobposting/"]')
        logger.info(f"[Guichet-Emplois] {len(cards)} liens jobposting trouves")

        if not cards:
            # Fallback: any link that looks like a job posting
            cards = soup.select('a.jobposting')
            logger.info(f"[Guichet-Emplois] {len(cards)} a.jobposting (fallback)")

        for card in cards:
            try:
                href = card.get('href', '')
                if not href:
                    continue
                if not href.startswith('http'):
                    href = self.BASE_URL + href

                # Extract title from heading or first significant text
                title = ''
                title_el = card.select_one('h3, h2, h4, span.noctitle')
                if title_el:
                    title = title_el.get_text(strip=True)
                if not title:
                    # Get the first line of text as title
                    title = card.get_text(' ', strip=True).split('\n')[0].strip()
                if not title or len(title) < 5:
                    continue

                # Parse <li> elements inside the card for metadata
                company = ''
                location_text = ''
                salary = ''
                date_posted = ''

                li_elements = card.select('li')
                for li in li_elements:
                    text = li.get_text(strip=True)
                    if not text or text == title:
                        continue

                    text_lower = text.lower()

                    # Salary detection
                    if '$' in text or '/h' in text_lower or 'heure' in text_lower or 'annuel' in text_lower:
                        salary = text
                    # Location detection
                    elif any(loc in text_lower for loc in ['(qc)', '(on)', '(bc)', '(ab)', 'québec', 'quebec', 'montréal', 'montreal', 'laval']):
                        location_text = text
                    # Date detection
                    elif re.search(r'\d{4}-\d{2}-\d{2}', text) or 'posted' in text_lower or 'publi' in text_lower:
                        date_posted = text
                    # Company (first unmatched short text)
                    elif not company and len(text) < 100:
                        company = text

                # Detect work type from badges/labels
                card_text = card.get_text(' ', strip=True).lower()
                work_type = ''
                if 'hybrid' in card_text or 'hybride' in card_text:
                    work_type = 'hybride'
                elif 'remote' in card_text or 'télétravail' in card_text or 'teletravail' in card_text:
                    work_type = 'teletravail'
                elif 'on-site' in card_text or 'présentiel' in card_text or 'sur place' in card_text:
                    work_type = 'presentiel'

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location_text,
                    'url': href,
                    'salary': salary,
                    'work_type': work_type,
                    'date_posted': date_posted,
                    'description': '',
                })
            except Exception as e:
                logger.debug(f"[Guichet-Emplois] Erreur parsing carte: {e}")
                continue

        return jobs
