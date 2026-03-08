import logging
import requests
from config import Config
from scrapers.base import extract_highlights

logger = logging.getLogger(__name__)


class AdzunaScraper:
    """Adzuna job search via their official API (Canada)."""
    SOURCE_NAME = 'Adzuna'

    def _detect_work_type(self, text):
        text_lower = text.lower()
        if 'télétravail' in text_lower or 'remote' in text_lower or 'teletravail' in text_lower:
            return 'teletravail'
        elif 'hybride' in text_lower or 'hybrid' in text_lower:
            return 'hybride'
        elif 'présentiel' in text_lower or 'sur place' in text_lower or 'on-site' in text_lower:
            return 'presentiel'
        return ''

    @staticmethod
    def _normalize_job_type(text):
        if not text:
            return ''
        t = text.lower().strip()
        if any(w in t for w in ['full_time', 'full time', 'permanent', 'temps plein']):
            return 'Temps plein'
        if any(w in t for w in ['part_time', 'part time', 'temps partiel']):
            return 'Temps partiel'
        if any(w in t for w in ['contract', 'contrat', 'temporaire']):
            return 'Contrat'
        return text.strip()

    def scrape(self, keywords, location='Montreal'):
        app_id = Config.ADZUNA_APP_ID
        app_key = Config.ADZUNA_APP_KEY
        if not app_id or not app_key:
            logger.warning("[Adzuna] API credentials missing (ADZUNA_APP_ID / ADZUNA_APP_KEY)")
            return []

        all_jobs = []
        for keyword in keywords:
            try:
                logger.info(f"[Adzuna] Recherche API: {keyword} @ {location}")
                url = (
                    f"https://api.adzuna.com/v1/api/jobs/ca/search/1"
                    f"?app_id={app_id}&app_key={app_key}"
                    f"&results_per_page=25"
                    f"&what={requests.utils.quote(keyword)}"
                    f"&where={requests.utils.quote(location)}"
                    f"&content-type=application/json"
                )

                response = requests.get(url, timeout=15)
                logger.info(f"[Adzuna] Status: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"[Adzuna] Erreur API: {response.status_code} - {response.text[:200]}")
                    continue

                data = response.json()
                results = data.get('results', [])
                logger.info(f"[Adzuna] {len(results)} resultats pour '{keyword}'")

                for item in results:
                    title = item.get('title', '').strip()
                    if not title:
                        continue

                    redirect_url = item.get('redirect_url', '')
                    if not redirect_url:
                        continue

                    company_obj = item.get('company', {})
                    company = company_obj.get('display_name', '') if isinstance(company_obj, dict) else ''

                    location_obj = item.get('location', {})
                    loc = location_obj.get('display_name', '') if isinstance(location_obj, dict) else ''

                    description = item.get('description', '')

                    # Salary
                    salary = ''
                    salary_min = item.get('salary_min')
                    salary_max = item.get('salary_max')
                    if salary_min and salary_max:
                        salary = f"${int(salary_min):,} - ${int(salary_max):,}"
                    elif salary_min:
                        salary = f"${int(salary_min):,}+"
                    elif salary_max:
                        salary = f"Jusqu'a ${int(salary_max):,}"

                    work_type = self._detect_work_type(
                        title + ' ' + description + ' ' + loc
                    )

                    contract_type = item.get('contract_type', '')
                    contract_time = item.get('contract_time', '')
                    raw_type = ' '.join(filter(None, [contract_time, contract_type]))
                    job_type = self._normalize_job_type(raw_type)

                    all_jobs.append({
                        'title': title,
                        'company': company,
                        'location': loc,
                        'url': redirect_url,
                        'salary': salary,
                        'work_type': work_type,
                        'job_type': job_type,
                        'description': description[:800] if description else '',
                        'source': self.SOURCE_NAME,
                        'date_posted': item.get('created', ''),
                        'highlights': extract_highlights(title + ' ' + description),
                    })

            except Exception as e:
                logger.error(f"[Adzuna] Erreur '{keyword}': {e}")
                continue

        return all_jobs
