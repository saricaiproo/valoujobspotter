import logging
import re
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class IndeedScraper(BaseScraper):
    SOURCE_NAME = 'Indeed'
    BASE_URL = 'https://ca.indeed.com'

    def build_search_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        loc = quote_plus(location)
        # Use Indeed RSS feed - much less likely to be blocked
        return f"{self.BASE_URL}/rss?q={kw}&l={loc}&sort=date"

    def scrape(self, keywords, location='Montreal'):
        all_jobs = []
        for keyword in keywords:
            try:
                url = self.build_search_url(keyword, location)
                logger.info(f"[{self.SOURCE_NAME}] Recherche RSS: {keyword} @ {location}")
                soup = self._get_soup(url)
                if soup is None:
                    continue
                jobs = self.parse_listing(soup)
                for job in jobs:
                    job['source'] = self.SOURCE_NAME
                all_jobs.extend(jobs)
                logger.info(f"[{self.SOURCE_NAME}] {len(jobs)} offres trouvees pour '{keyword}'")
            except Exception as e:
                logger.error(f"[{self.SOURCE_NAME}] Erreur scraping '{keyword}': {e}")
                continue
        return all_jobs

    def parse_listing(self, soup):
        jobs = []
        items = soup.find_all('item')

        for item in items:
            try:
                title_el = item.find('title')
                link_el = item.find('link')
                if not title_el or not link_el:
                    continue

                title = title_el.get_text(strip=True)
                link = link_el.get_text(strip=True)
                if not link:
                    # Sometimes link is in next sibling text node
                    link = link_el.next_sibling
                    if link:
                        link = str(link).strip()

                if not link or not link.startswith('http'):
                    continue

                # Extract company and location from title or description
                source_el = item.find('source')
                company = source_el.get_text(strip=True) if source_el else ''

                desc_el = item.find('description')
                description = desc_el.get_text(strip=True) if desc_el else ''

                pub_date = ''
                date_el = item.find('pubdate')
                if date_el:
                    pub_date = date_el.get_text(strip=True)

                # Try to extract location from description
                location = self._extract_location(description)
                work_type = self._detect_work_type(title + ' ' + description)

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': link,
                    'salary': '',
                    'work_type': work_type,
                    'date_posted': pub_date,
                    'description': description[:500],
                })
            except Exception as e:
                logger.debug(f"[Indeed] Erreur parsing item RSS: {e}")
                continue

        return jobs

    def _extract_location(self, text):
        text_lower = text.lower()
        if 'montreal' in text_lower or 'montréal' in text_lower:
            return 'Montreal, QC'
        if 'laval' in text_lower:
            return 'Laval, QC'
        if 'longueuil' in text_lower:
            return 'Longueuil, QC'
        return ''

    def _detect_work_type(self, text):
        text_lower = text.lower()
        if 'télétravail' in text_lower or 'remote' in text_lower or 'teletravail' in text_lower:
            return 'teletravail'
        elif 'hybride' in text_lower or 'hybrid' in text_lower:
            return 'hybride'
        elif 'présentiel' in text_lower or 'sur place' in text_lower or 'on-site' in text_lower:
            return 'presentiel'
        return ''
