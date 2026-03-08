import logging
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class JobillicoScraper(BaseScraper):
    SOURCE_NAME = 'Jobillico'
    BASE_URL = 'https://www.jobillico.com'

    def build_search_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        loc = quote_plus(location)
        return f"{self.BASE_URL}/recherche-emploi?skwd={kw}&sloc={loc}"

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
                    # Fallback: check list items
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
                    # Clean up excessive whitespace in salary
                    salary = ' '.join(salary.split())

                # Job type (temps plein, etc.)
                job_type = ''
                clock_icon = card.select_one('span.icon--information--clock')
                if clock_icon:
                    type_p = clock_icon.find_next_sibling('p')
                    if type_p:
                        job_type = type_p.get_text(strip=True)

                work_type = self._detect_work_type(title + ' ' + location + ' ' + job_type)

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
        import re

        # Description
        desc_el = soup.select_one(
            'div.job-description, div[class*="description"], '
            'div.offer__content, section.offer__description'
        )
        if desc_el:
            desc = desc_el.get_text(' ', strip=True)
            desc = re.sub(r'\s+', ' ', desc)
            job['description'] = desc[:800]

        # Try to get salary from detail page if missing
        if not job.get('salary'):
            page_text = soup.get_text(' ', strip=True)
            sal_match = re.search(
                r'(\d[\d\s]*[\d]\s*\$|\$\s*\d[\d\s,\.]*[\d])\s*(?:[-àa]\s*(\d[\d\s]*[\d]\s*\$|\$\s*\d[\d\s,\.]*[\d]))?',
                page_text
            )
            if sal_match:
                job['salary'] = sal_match.group(0).strip()

        # Try to get job type from detail page
        if not job.get('job_type'):
            info_items = soup.select('li.list__item, div.offer__info-item')
            for item in info_items:
                text = item.get_text(strip=True).lower()
                normalized = self.normalize_job_type(text)
                if normalized and normalized != text:
                    job['job_type'] = normalized
                    break

        return job

    def _detect_work_type(self, text):
        text_lower = text.lower()
        if 'télétravail' in text_lower or 'remote' in text_lower or 'teletravail' in text_lower:
            return 'teletravail'
        elif 'hybride' in text_lower or 'hybrid' in text_lower:
            return 'hybride'
        elif 'présentiel' in text_lower or 'sur place' in text_lower:
            return 'presentiel'
        return ''
