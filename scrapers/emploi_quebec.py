import logging
import re
import requests
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Montreal region code for Emploi Québec
REGION_MONTREAL = '06'
REGION_LAVAL = '13'
REGION_MONTEREGIE = '16'
REGION_LANAUDIERE = '14'
REGION_LAURENTIDES = '15'

MONTREAL_AREA_REGIONS = [
    REGION_MONTREAL, REGION_LAVAL, REGION_MONTEREGIE,
    REGION_LANAUDIERE, REGION_LAURENTIDES,
]


class EmploiQuebecScraper(BaseScraper):
    SOURCE_NAME = 'Emploi-Québec'
    BASE_URL = 'https://www.quebecemploi.gouv.qc.ca'
    SEARCH_URL = BASE_URL + '/search/postingFilteredAI'
    DETAIL_URL = BASE_URL + '/manitouLS/cache/postingJsonCS'

    def build_search_url(self, keyword, location='Montreal'):
        # Not used — we use the API directly
        return self.SEARCH_URL

    def _search_api(self, keyword, regions=None, page=1):
        """Call the Emploi Québec search API."""
        if regions is None:
            regions = MONTREAL_AREA_REGIONS

        payload = {
            "sort": {"type": "AUTO"},
            "langue": "fr",
            "page": page,
            "filter": {
                "inputSearch": keyword,
                "address": "",
                "localisation": {"longitude": "", "latitude": "", "distance": 20},
                "adminRegion": regions,
                "offerType": [],
                "commitment": [],
                "jobDuration": [],
                "levelEducation": [],
                "studyDiscipline": [],
                "mrc": [],
                "bsq": [],
                "scian": [],
                "postedSince": "7",  # Last 7 days
                "excludeAgencies": False,
                "isUkrainian": False,
                "isExperimente": False,
                "isSubsidized": False,
                "isTrainingProgram": False,
            }
        }

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': self.session.headers.get('User-Agent', ''),
        }

        try:
            self._delay()
            response = requests.post(self.SEARCH_URL, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"[Emploi-Québec] Erreur API recherche: {e}")
            return None

    def _get_detail(self, posting_id):
        """Fetch full job details from the API."""
        url = f"{self.DETAIL_URL}/{posting_id}/fr"
        try:
            response = requests.get(url, timeout=15, headers={
                'Accept': 'application/json',
                'User-Agent': self.session.headers.get('User-Agent', ''),
            })
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.debug(f"[Emploi-Québec] Erreur détail {posting_id}: {e}")
        return None

    def scrape(self, keywords, location='Montreal'):
        all_jobs = []
        for keyword in keywords:
            try:
                logger.info(f"[Emploi-Québec] Recherche: {keyword}")
                data = self._search_api(keyword)
                if not data:
                    continue

                items = data.get('items', [])
                total = data.get('meta', {}).get('total_hits', 0)
                logger.info(f"[Emploi-Québec] {len(items)} résultats (total: {total}) pour '{keyword}'")

                for item in items[:50]:  # Cap at 50 per keyword
                    try:
                        posting_id = item.get('ide_affch')
                        if not posting_id:
                            continue

                        title = item.get('titre', '').strip()
                        if not title:
                            continue

                        company = item.get('employeur', '').strip()
                        city = item.get('nom_ville', '').strip()
                        expiry = item.get('expiration_date', '')

                        url = f"https://www.quebecemploi.gouv.qc.ca/plateforme-emploi/offre/{posting_id}"

                        job = {
                            'title': title.title() if title == title.lower() else title,
                            'company': company.title() if company == company.upper() else company,
                            'location': city,
                            'url': url,
                            'salary': '',
                            'work_type': '',
                            'job_type': '',
                            'date_posted': expiry,  # Will be replaced by detail if available
                            'description': '',
                            'source': self.SOURCE_NAME,
                            '_posting_id': posting_id,
                        }
                        all_jobs.append(job)
                    except Exception as e:
                        logger.debug(f"[Emploi-Québec] Erreur parsing item: {e}")
                        continue

            except Exception as e:
                logger.error(f"[Emploi-Québec] Erreur scraping '{keyword}': {e}")
                continue

        return all_jobs

    def enrich_jobs_batch(self, jobs, max_jobs=20):
        """Enrich jobs by fetching detail pages from the API."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        to_enrich = [j for j in jobs if j.get('_posting_id')][:max_jobs]
        if not to_enrich:
            return jobs

        logger.info(f"[Emploi-Québec] Enrichissement de {len(to_enrich)} offres...")

        def fetch_detail(job):
            posting_id = job['_posting_id']
            detail = self._get_detail(posting_id)
            return job, detail

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(fetch_detail, j) for j in to_enrich]
            for future in as_completed(futures):
                try:
                    job, detail = future.result()
                    if not detail:
                        continue
                    self._apply_detail(job, detail)
                except Exception as e:
                    logger.debug(f"[Emploi-Québec] Erreur enrichissement: {e}")

        # Remove internal field
        for job in jobs:
            job.pop('_posting_id', None)

        return jobs

    def _apply_detail(self, job, detail):
        """Apply detail API data to job dict."""
        # Description
        desc = detail.get('description', '')
        if desc:
            # Strip HTML tags
            desc = re.sub(r'<[^>]+>', ' ', desc)
            desc = re.sub(r'\s+', ' ', desc).strip()
            job['description'] = desc[:3000]

        # Salary
        salary_min = detail.get('salaireMinimum')
        salary_max = detail.get('salaireMaximum')
        salary_type = detail.get('typeSalaire', '')
        if salary_min or salary_max:
            if salary_min and salary_max:
                job['salary'] = f"{salary_min}$ - {salary_max}$ / {salary_type}"
            elif salary_min:
                job['salary'] = f"{salary_min}$ / {salary_type}"

        # Job type from commitment
        engagement = detail.get('engagement', '')
        if engagement:
            job['job_type'] = self.normalize_job_type(engagement)

        # Work type from description
        full_text = f"{job.get('title', '')} {job.get('description', '')}"
        if not job.get('work_type'):
            job['work_type'] = self._detect_work_type(full_text)

        # Date posted
        date_pub = detail.get('datePublication') or detail.get('dateDebut')
        if date_pub:
            job['date_posted'] = date_pub

        # Location from detail
        ville = detail.get('nomVille', '')
        if ville and not job.get('location'):
            job['location'] = ville

        # Highlights
        from scrapers.base import extract_highlights
        job['highlights'] = extract_highlights(full_text)

        logger.info(f"  + {job.get('title', '')[:45]} | "
                    f"mode={job.get('work_type') or '?'} "
                    f"type={job.get('job_type') or '?'} "
                    f"sal={'oui' if job.get('salary') else 'non'}")
