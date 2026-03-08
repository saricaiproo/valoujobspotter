import time
import random
import logging
import requests
from bs4 import BeautifulSoup
from config import Config

logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
]


class BaseScraper:
    SOURCE_NAME = 'base'
    BASE_URL = ''

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'fr-CA,fr;q=0.9,en-CA;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })

    def _delay(self):
        time.sleep(random.uniform(Config.SCRAPE_DELAY_MIN, Config.SCRAPE_DELAY_MAX))

    def _get_soup(self, url):
        try:
            self._delay()
            logger.info(f"[{self.SOURCE_NAME}] GET {url}")
            response = self.session.get(url, timeout=30)
            logger.info(f"[{self.SOURCE_NAME}] Status: {response.status_code}, Taille: {len(response.text)} chars")
            response.raise_for_status()
            return BeautifulSoup(response.text, 'lxml')
        except requests.RequestException as e:
            logger.error(f"[{self.SOURCE_NAME}] Erreur requete {url}: {e}")
            return None

    def build_search_url(self, keyword, location='Montreal'):
        raise NotImplementedError

    def parse_listing(self, soup):
        raise NotImplementedError

    def scrape(self, keywords, location='Montreal'):
        all_jobs = []
        for keyword in keywords:
            try:
                url = self.build_search_url(keyword, location)
                logger.info(f"[{self.SOURCE_NAME}] Recherche: {keyword} @ {location}")
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
