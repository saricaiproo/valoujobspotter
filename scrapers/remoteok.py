import logging
import requests
from scrapers.base import extract_highlights

logger = logging.getLogger(__name__)


class RemoteOKScraper:
    """RemoteOK job search via their free public JSON API."""
    SOURCE_NAME = 'RemoteOK'

    def _detect_work_type(self, text):
        # Everything on RemoteOK is remote by definition
        return 'teletravail'

    def scrape(self, keywords, location='Montreal'):
        all_jobs = []
        seen_urls = set()

        for keyword in keywords:
            try:
                logger.info(f"[RemoteOK] Recherche: {keyword}")
                url = f"https://remoteok.com/api?tag={requests.utils.quote(keyword)}"
                headers = {
                    'User-Agent': 'ValouJobScout/1.0',
                    'Accept': 'application/json',
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
                        'description': description[:800] if description else '',
                        'source': self.SOURCE_NAME,
                        'date_posted': item.get('date', ''),
                        'highlights': extract_highlights(title + ' ' + description),
                    })

            except Exception as e:
                logger.error(f"[RemoteOK] Erreur '{keyword}': {e}")
                continue

        return all_jobs
