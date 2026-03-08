import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class GoogleJobsScraper:
    """
    Scrapes job listings from Google search results.
    Lower priority source - if a job already exists from another source, skip it.
    """
    SOURCE_NAME = 'Google Jobs'
    PRIORITY = 99  # Highest number = lowest priority in dedup

    def _detect_work_type(self, text):
        text_lower = text.lower()
        if 'télétravail' in text_lower or 'remote' in text_lower or 'teletravail' in text_lower:
            return 'teletravail'
        elif 'hybride' in text_lower or 'hybrid' in text_lower:
            return 'hybride'
        elif 'présentiel' in text_lower or 'sur place' in text_lower or 'on-site' in text_lower:
            return 'presentiel'
        return ''

    def scrape(self, keywords, location='Montreal'):
        all_jobs = []
        seen_urls = set()

        for keyword in keywords:
            try:
                logger.info(f"[Google Jobs] Recherche: {keyword} @ {location}")
                query = requests.utils.quote(f"{keyword} emploi {location}")
                url = f"https://www.google.com/search?q={query}&ibp=htl;jobs"

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept-Language': 'fr-CA,fr;q=0.9,en;q=0.7',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                }

                response = requests.get(url, headers=headers, timeout=15)
                logger.info(f"[Google Jobs] Status: {response.status_code}, Taille: {len(response.text)} chars")

                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, 'lxml')

                # Google Jobs embeds job data in script tags or structured divs
                # Try to find job listing elements
                cards = soup.select('div.xpd, div[jscontroller] div[data-ved], li[data-entityid]')
                logger.info(f"[Google Jobs] {len(cards)} cartes trouvees")

                if not cards:
                    # Fallback: look for any structured job data in the page
                    # Google sometimes renders jobs differently
                    job_divs = soup.select('div[class*="job"], div[data-jobid]')
                    logger.info(f"[Google Jobs] {len(job_divs)} divs job (fallback)")
                    cards = job_divs

                for card in cards:
                    try:
                        # Title
                        title_el = card.select_one('div[role="heading"], h2, h3, div.BjJfJf')
                        if not title_el:
                            continue
                        title = title_el.get_text(strip=True)
                        if not title or len(title) < 5:
                            continue

                        # Company
                        company = ''
                        company_el = card.select_one('div.vNEEBe, div[class*="company"], span[class*="company"]')
                        if company_el:
                            company = company_el.get_text(strip=True)

                        # Location
                        loc = ''
                        loc_el = card.select_one('div.Qk80Jf, div[class*="location"]')
                        if loc_el:
                            loc = loc_el.get_text(strip=True)

                        # Link - Google Jobs links to external sites
                        link_el = card.select_one('a[href*="http"]')
                        link = ''
                        if link_el:
                            link = link_el.get('href', '')
                            # Clean Google redirect
                            if '/url?q=' in link:
                                link = link.split('/url?q=')[1].split('&')[0]

                        if not link or link in seen_urls:
                            continue
                        seen_urls.add(link)

                        work_type = self._detect_work_type(title + ' ' + loc)

                        all_jobs.append({
                            'title': title,
                            'company': company,
                            'location': loc,
                            'url': link,
                            'salary': '',
                            'work_type': work_type,
                            'description': '',
                            'source': self.SOURCE_NAME,
                        })
                    except Exception:
                        continue

                logger.info(f"[Google Jobs] {len(all_jobs)} offres pour '{keyword}'")

            except Exception as e:
                logger.error(f"[Google Jobs] Erreur '{keyword}': {e}")
                continue

        return all_jobs
