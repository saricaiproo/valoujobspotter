import re
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

# Skills/requirements to look for in job descriptions
SKILL_PATTERNS = [
    # Tools & platforms
    (r'\b(instagram)\b', 'Instagram'),
    (r'\b(facebook)\b', 'Facebook'),
    (r'\b(tiktok)\b', 'TikTok'),
    (r'\b(linkedin)\b', 'LinkedIn'),
    (r'\b(twitter|x\.com)\b', 'Twitter/X'),
    (r'\b(pinterest)\b', 'Pinterest'),
    (r'\b(youtube)\b', 'YouTube'),
    (r'\b(hootsuite)\b', 'Hootsuite'),
    (r'\b(sprout\s*social)\b', 'Sprout Social'),
    (r'\b(buffer)\b', 'Buffer'),
    (r'\b(canva)\b', 'Canva'),
    (r'\b(photoshop)\b', 'Photoshop'),
    (r'\b(illustrator)\b', 'Illustrator'),
    (r'\b(adobe\s*(creative\s*)?suite|adobe\s*cc)\b', 'Adobe Suite'),
    (r'\b(figma)\b', 'Figma'),
    (r'\b(google\s*analytics|ga4)\b', 'Google Analytics'),
    (r'\b(google\s*ads)\b', 'Google Ads'),
    (r'\b(meta\s*ads|facebook\s*ads)\b', 'Meta Ads'),
    (r'\b(mailchimp)\b', 'Mailchimp'),
    (r'\b(hubspot)\b', 'HubSpot'),
    (r'\b(wordpress)\b', 'WordPress'),
    (r'\b(shopify)\b', 'Shopify'),
    (r'\b(seo)\b', 'SEO'),
    (r'\b(sem)\b', 'SEM'),
    (r'\b(crm)\b', 'CRM'),
    (r'\b(html|css)\b', 'HTML/CSS'),
    (r'\b(excel)\b', 'Excel'),
    (r'\b(powerpoint)\b', 'PowerPoint'),
    (r'\b(salesforce)\b', 'Salesforce'),
    # Languages
    (r'\b(bilingue|bilingual)\b', 'Bilingue'),
    (r'\b(fran[cç]ais\s*(et|and|\/)\s*anglais|anglais\s*(et|and|\/)\s*fran[cç]ais)\b', 'Bilingue'),
    (r'\b(trilingue|trilingual)\b', 'Trilingue'),
    # Experience
    (r'\b(\d+)\s*[\-\+à]\s*(\d+)?\s*an(?:s|nées?)?\s*(?:d\'?expérience|d\'?experience|experience)', None),  # handled specially
    (r'\b(\d+)\s*(?:ans?|years?)\s*(?:d\'?expérience|d\'?experience|experience|\+)', None),
    # Qualifications
    (r'\b(baccalaur[ée]at|bachelor|bac)\b', 'BAC'),
    (r'\b(ma[iî]trise|master|mba)\b', 'Maitrise'),
    (r'\b(diplôme|diplome|dec|aec)\b', 'Diplome'),
]

# Experience patterns - extracted separately for better formatting
EXP_PATTERNS = [
    (r'(\d+)\s*[\-à]\s*(\d+)\s*an(?:s|nées?)', lambda m: f"{m.group(1)}-{m.group(2)} ans exp."),
    (r'(\d+)\s*\+?\s*an(?:s|nées?)\s*(?:d\'?exp[ée]rience|d\'?experience|experience)', lambda m: f"{m.group(1)}+ ans exp."),
    (r'(\d+)\s*(?:years?)\s*(?:of\s*)?experience', lambda m: f"{m.group(1)}+ ans exp."),
]


def extract_highlights(text):
    """Extract key skills, tools, and requirements from job text."""
    if not text:
        return []

    text_lower = text.lower()
    highlights = []
    seen = set()

    # Extract experience requirements first
    for pattern, formatter in EXP_PATTERNS:
        match = re.search(pattern, text_lower)
        if match and 'exp' not in seen:
            highlights.append(formatter(match))
            seen.add('exp')
            break

    # Extract skills/tools
    for pattern, label in SKILL_PATTERNS:
        if label is None:
            continue  # skip experience patterns already handled
        if label not in seen and re.search(pattern, text_lower):
            highlights.append(label)
            seen.add(label)

    return highlights[:8]  # max 8 highlights per job


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

    def parse_detail(self, soup, job):
        """Override in subclass to extract extra info from detail page.
        Should return updated job dict with enriched fields."""
        return job

    @staticmethod
    def normalize_job_type(text):
        """Normalize job type to standard values."""
        if not text:
            return ''
        t = text.lower().strip()
        if any(w in t for w in ['temps plein', 'full time', 'full-time', 'permanent', 'temps complet']):
            return 'Temps plein'
        if any(w in t for w in ['temps partiel', 'part time', 'part-time']):
            return 'Temps partiel'
        if any(w in t for w in ['contrat', 'contract', 'contractuel', 'temporaire']):
            return 'Contrat'
        if any(w in t for w in ['stage', 'intern', 'stagiaire']):
            return 'Stage'
        if any(w in t for w in ['pigiste', 'freelance', 'autonome']):
            return 'Pigiste'
        return text.strip()

    @staticmethod
    def _detect_work_type(text):
        text_lower = text.lower()
        if 'télétravail' in text_lower or 'remote' in text_lower or 'teletravail' in text_lower:
            return 'teletravail'
        elif 'hybride' in text_lower or 'hybrid' in text_lower:
            return 'hybride'
        elif 'présentiel' in text_lower or 'sur place' in text_lower or 'on-site' in text_lower:
            return 'presentiel'
        return ''

    def enrich_job(self, job):
        """Fetch detail page and extract additional info."""
        url = job.get('url', '')
        if not url:
            return job

        try:
            soup = self._get_soup(url)
            if soup is None:
                return job

            # Let subclass extract specific fields
            job = self.parse_detail(soup, job)

            # Extract full page text for skill detection
            page_text = soup.get_text(' ', strip=True)

            # If description is still empty, try to get it from the page
            if not job.get('description'):
                # Look for common description containers
                desc_el = soup.select_one(
                    'div.description, div.job-description, section.description, '
                    'div[class*="description"], div[class*="content"], article'
                )
                if desc_el:
                    desc_text = desc_el.get_text(' ', strip=True)
                    # Clean up
                    desc_text = re.sub(r'\s+', ' ', desc_text)
                    job['description'] = desc_text[:800]

            # Extract highlights from description + full page
            full_text = (job.get('description', '') + ' ' + page_text)
            job['highlights'] = extract_highlights(full_text)

            # Try to fill missing fields from detail page
            if not job.get('work_type'):
                job['work_type'] = self._detect_work_type(page_text)
            if not job.get('job_type'):
                job['job_type'] = self.normalize_job_type(page_text[:500])

        except Exception as e:
            logger.debug(f"[{self.SOURCE_NAME}] Erreur enrichissement {url}: {e}")

        return job

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
                    job['job_type'] = self.normalize_job_type(job.get('job_type', ''))
                all_jobs.extend(jobs)
                logger.info(f"[{self.SOURCE_NAME}] {len(jobs)} offres trouvees pour '{keyword}'")
            except Exception as e:
                logger.error(f"[{self.SOURCE_NAME}] Erreur scraping '{keyword}': {e}")
                continue
        return all_jobs
