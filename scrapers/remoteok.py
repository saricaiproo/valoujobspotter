import logging
import random
import requests
from scrapers.base import extract_highlights, USER_AGENTS

logger = logging.getLogger(__name__)


class RemoteOKScraper:
    """RemoteOK job search via their free public JSON API."""
    SOURCE_NAME = 'RemoteOK'

    def _detect_work_type(self, text):
        # Everything on RemoteOK is remote by definition
        return 'teletravail'

    # Map French keywords to English equivalents for this English-only site
    KEYWORD_MAP = {
        'médias sociaux': 'social media',
        'medias sociaux': 'social media',
        'marketing numérique': 'digital marketing',
        'marketing numerique': 'digital marketing',
        'gestionnaire de contenu': 'content manager',
        'chargé de communication': 'communications',
        'charge de communication': 'communications',
        'coordonnateur marketing': 'marketing coordinator',
        'community manager': 'community manager',
        'social media': 'social media',
        'content manager': 'content manager',
        'marketing coordinator': 'marketing coordinator',
        'brand manager': 'brand manager',
    }

    def _translate_keyword(self, keyword):
        """Convert French keyword to English for RemoteOK search."""
        kw_lower = keyword.lower()
        if kw_lower in self.KEYWORD_MAP:
            return self.KEYWORD_MAP[kw_lower]
        return keyword

    def scrape(self, keywords, location='Montreal'):
        all_jobs = []
        seen_urls = set()
        seen_keywords = set()

        for keyword in keywords:
            # Translate to English and deduplicate
            en_keyword = self._translate_keyword(keyword)
            if en_keyword.lower() in seen_keywords:
                continue
            seen_keywords.add(en_keyword.lower())
            keyword = en_keyword
            try:
                logger.info(f"[RemoteOK] Recherche: {keyword}")
                url = f"https://remoteok.com/api?tag={requests.utils.quote(keyword)}"
                headers = {
                    'User-Agent': random.choice(USER_AGENTS),
                    'Accept': 'application/json',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://remoteok.com/',
                }
                response = requests.get(url, headers=headers, timeout=15)
                logger.info(f"[RemoteOK] Status: {response.status_code}")

                if response.status_code != 200:
                    continue

                data = response.json()
                # First element is a metadata/legal notice object
                results = [item for item in data if isinstance(item, dict) and item.get('id')]
                logger.info(f"[RemoteOK] {len(results)} resultats pour '{keyword}'")

                for item in results:
                    job_url = item.get('url', '')
                    if not job_url:
                        slug = item.get('slug', '')
                        if slug:
                            job_url = f"https://remoteok.com/remote-jobs/{slug}"
                    if not job_url or job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    title = item.get('position', '').strip()
                    if not title:
                        continue

                    company = item.get('company', '').strip()
                    location_str = item.get('location', 'Remote').strip()
                    description = item.get('description', '')
                    # Clean HTML tags from description
                    if description:
                        import re
                        description = re.sub(r'<[^>]+>', ' ', description)
                        description = ' '.join(description.split())

                    salary = ''
                    sal_min = item.get('salary_min')
                    sal_max = item.get('salary_max')
                    if sal_min and sal_max:
                        salary = f"${int(sal_min):,} - ${int(sal_max):,} USD"
                    elif sal_min:
                        salary = f"${int(sal_min):,}+ USD"

                    tags = item.get('tags', [])

                    all_jobs.append({
                        'title': title,
                        'company': company,
                        'location': location_str or 'Remote',
                        'url': job_url,
                        'salary': salary,
                        'work_type': 'teletravail',
                        'job_type': ', '.join(tags[:3]) if tags else '',
                        'description': description[:3000] if description else '',
                        'source': self.SOURCE_NAME,
                        'date_posted': item.get('date', ''),
                        'highlights': extract_highlights(title + ' ' + description),
                    })

            except Exception as e:
                logger.error(f"[RemoteOK] Erreur '{keyword}': {e}")
                continue

        return all_jobs
