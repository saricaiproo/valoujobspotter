import logging
import re
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class JobillicoScraper(BaseScraper):
    SOURCE_NAME = 'Jobillico'
    BASE_URL = 'https://www.jobillico.com'

    def build_search_url(self, keyword, location='Montreal', page=1):
        kw = quote_plus(keyword)
        loc = quote_plus(location)
        # sort=1 = by date (most recent first)
        url = f"{self.BASE_URL}/recherche-emploi?skwd={kw}&sloc={loc}&sort=1"
        if page > 1:
            url += f"&page={page}"
        return url

    def scrape(self, keywords, location='Montreal'):
        """Override to add pagination — scrape pages 1-3 for each keyword."""
        all_jobs = []
        for keyword in keywords:
            for page in range(1, 4):  # pages 1, 2, 3
                try:
                    url = self.build_search_url(keyword, location, page=page)
                    logger.info(f"[Jobillico] Recherche: {keyword} @ {location} (page {page})")
                    soup = self._get_soup(url)
                    if soup is None:
                        break
                    jobs = self.parse_listing(soup)
                    if not jobs:
                        break
                    for job in jobs:
                        job['source'] = self.SOURCE_NAME
                        job['job_type'] = self.normalize_job_type(job.get('job_type', ''))
                    all_jobs.extend(jobs)
                    logger.info(f"[Jobillico] {len(jobs)} offres page {page} pour '{keyword}'")
                    if len(jobs) < 5:
                        break
                except Exception as e:
                    logger.error(f"[Jobillico] Erreur scraping '{keyword}' page {page}: {e}")
                    break
        return all_jobs

    def parse_listing(self, soup):
        jobs = []
        cards = soup.select('article.card.card--clickable')

        logger.info(f"[Jobillico] {len(cards)} cartes trouvees dans le HTML")

        for card in cards:
            try:
                # Job title is in h2 > a (NOT h3 which is company)
                title_el = card.select_one('h2 a')
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if not title:
                    continue

                link = title_el.get('href', '')
                if link and not link.startswith('http'):
                    link = self.BASE_URL + link
                if not link:
                    continue

                # Skip company profile links - we only want job postings
                if '/voir-entreprise/' in link:
                    continue

                # Company name is in h3.h4 > a.companyLink or span.companyLink
                company = ''
                company_el = card.select_one('h3.h4 a.companyLink, h3.h4 span.companyLink, h3.h4')
                if company_el:
                    company = company_el.get_text(strip=True)

                # Location: li with position icon, then sibling p
                location = ''
                loc_icon = card.select_one('span.icon--information--position')
                if loc_icon:
                    loc_p = loc_icon.find_next_sibling('p')
                    if loc_p:
                        location = loc_p.get_text(strip=True)
                if not location:
                    for li in card.select('li.list__item'):
                        text = li.get_text(strip=True)
                        if any(loc in text.lower() for loc in ['qc', 'québec', 'quebec', 'montréal', 'montreal']):
                            location = text
                            break

                # Salary
                salary = ''
                salary_el = card.select_one('li.list__item--salary p')
                if salary_el:
                    salary = salary_el.get_text(strip=True)
                    salary = ' '.join(salary.split())

                # Job type (temps plein, etc.)
                job_type = ''
                clock_icon = card.select_one('span.icon--information--clock')
                if clock_icon:
                    type_p = clock_icon.find_next_sibling('p')
                    if type_p:
                        job_type = type_p.get_text(strip=True)

                # Get ALL card text for better detection
                card_text = card.get_text(' ', strip=True)

                work_type = self._detect_work_type(card_text)

                # Fallback detection from full card text
                if not job_type:
                    job_type = self.detect_job_type(card_text)
                if not salary:
                    salary = self.detect_salary(card_text)

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': link,
                    'salary': salary,
                    'work_type': work_type,
                    'job_type': job_type,
                    'description': '',
                })
            except Exception as e:
                logger.debug(f"[Jobillico] Erreur parsing carte: {e}")
                continue

        return jobs

    def parse_detail(self, soup, job):
        """Extract description, salary, and job type from Jobillico detail page."""
        # Description
        desc_el = soup.select_one(
            'div.job-description, div[class*="description"], '
            'div.offer__content, section.offer__description'
        )
        if desc_el:
            desc = desc_el.get_text(' ', strip=True)
            desc = re.sub(r'\s+', ' ', desc)
            job['description'] = desc[:3000]

        page_text = soup.get_text(' ', strip=True)

        # Fill missing fields from detail page
        if not job.get('salary'):
            job['salary'] = self.detect_salary(page_text)
        if not job.get('job_type'):
            job['job_type'] = self.detect_job_type(page_text)
        if not job.get('work_type'):
            job['work_type'] = self._detect_work_type(page_text)

        return job
