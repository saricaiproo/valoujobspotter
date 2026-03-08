import logging
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class GlassdoorScraper(BaseScraper):
    """
    Glassdoor Canada job search via Google cache/redirect.
    Uses the public listings page.
    """
    SOURCE_NAME = 'Glassdoor'
    BASE_URL = 'https://www.glassdoor.ca'

    def build_search_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        return f"{self.BASE_URL}/Job/montreal-{kw}-jobs-SRCH_IL.0,8_IC2280845_KO9,{9+len(keyword)}.htm?sortBy=date_desc"

    def parse_listing(self, soup):
        jobs = []
        cards = soup.select('li.JobsList_jobListItem__JBBUV, li[data-test="jobListing"], div.job-listing')

        for card in cards:
            try:
                title_el = card.select_one('a.JobCard_jobTitle__GLyJ1, a[data-test="job-title"], a.jobLink')
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                link = title_el.get('href', '')
                if link and not link.startswith('http'):
                    link = self.BASE_URL + link
                if not link:
                    continue

                company_el = card.select_one('span.EmployerProfile_compactEmployerName__9MGcV, div.employer-name, span[data-test="employer-name"]')
                company = company_el.get_text(strip=True) if company_el else ''

                location_el = card.select_one('div.JobCard_location__Ds1fM, span[data-test="emp-location"], div.location')
                location = location_el.get_text(strip=True) if location_el else ''

                salary_el = card.select_one('div.JobCard_salaryEstimate__QpbTW, span[data-test="detailSalary"]')
                salary = salary_el.get_text(strip=True) if salary_el else ''

                work_type = self._detect_work_type(title + ' ' + location)

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': link,
                    'salary': salary,
                    'work_type': work_type,
                    'description': '',
                })
            except Exception as e:
                logger.debug(f"[Glassdoor] Erreur parsing carte: {e}")
                continue

        return jobs

    def _detect_work_type(self, text):
        text_lower = text.lower()
        if 'remote' in text_lower or 'télétravail' in text_lower:
            return 'teletravail'
        elif 'hybrid' in text_lower or 'hybride' in text_lower:
            return 'hybride'
        elif 'on-site' in text_lower or 'présentiel' in text_lower:
            return 'presentiel'
        return ''
