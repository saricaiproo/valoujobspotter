import logging
from urllib.parse import quote_plus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class LinkedInScraper(BaseScraper):
    SOURCE_NAME = 'LinkedIn'
    BASE_URL = 'https://www.linkedin.com'

    def build_search_url(self, keyword, location='Montreal'):
        kw = quote_plus(keyword)
        return f"{self.BASE_URL}/jobs/search/?keywords={kw}&location=Montreal%2C+Quebec%2C+Canada&sortBy=DD"

    def parse_listing(self, soup):
        jobs = []
        cards = soup.select('div.base-search-card, div.job-search-card')

        logger.info(f"[LinkedIn] {len(cards)} cartes trouvees dans le HTML")

        for card in cards:
            try:
                title_el = card.select_one('h3.base-search-card__title')
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)

                link_el = card.select_one('a.base-card__full-link, a.base-search-card__full-link')
                link = link_el.get('href', '') if link_el else ''
                if not link:
                    continue

                # Clean LinkedIn tracking params
                if '?' in link:
                    link = link.split('?')[0]

                company_el = card.select_one('h4.base-search-card__subtitle, a.base-search-card__subtitle')
                company = company_el.get_text(strip=True) if company_el else ''

                location_el = card.select_one('span.job-search-card__location')
                location = location_el.get_text(strip=True) if location_el else ''

                date_el = card.select_one('time')
                date_posted = date_el.get('datetime', '') if date_el else ''

                # Get ALL text from card for better detection
                card_text = card.get_text(' ', strip=True)

                # Detect work type, job type, salary from full card text
                work_type = self._detect_work_type(card_text)
                job_type = self.detect_job_type(card_text)
                salary = self.detect_salary(card_text)

                # Also check metadata/badges
                badges = card.select('span.result-benefits__text, li.result-benefits__text')
                for badge in badges:
                    badge_text = badge.get_text(strip=True)
                    if not work_type:
                        work_type = self._detect_work_type(badge_text)
                    if not salary:
                        salary = self.detect_salary(badge_text)

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': link,
                    'salary': salary,
                    'work_type': work_type,
                    'job_type': job_type,
                    'date_posted': date_posted,
                    'description': '',
                })
            except Exception as e:
                logger.debug(f"[LinkedIn] Erreur parsing carte: {e}")
                continue

        return jobs

    def parse_detail(self, soup, job):
        """Extract description, work type, and job type from LinkedIn detail page."""
        import re

        # Description
        desc_el = soup.select_one(
            'div.description__text, div.show-more-less-html__markup, '
            'section.description div, div[class*="description"]'
        )
        if desc_el:
            desc = desc_el.get_text(' ', strip=True)
            desc = re.sub(r'\s+', ' ', desc)
            job['description'] = desc[:800]

        # Work type from criteria list
        criteria = soup.select('li.description__job-criteria-item')
        for item in criteria:
            label_el = item.select_one('h3')
            value_el = item.select_one('span')
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True).lower()
            value = value_el.get_text(strip=True)

            if 'type' in label and 'lieu' not in label:
                job['job_type'] = self.normalize_job_type(value)
            if 'lieu' in label or 'workplace' in label:
                if not job.get('work_type'):
                    job['work_type'] = self._detect_work_type(value)

        # Detect from full page text as fallback
        page_text = soup.get_text(' ', strip=True)
        if not job.get('work_type'):
            job['work_type'] = self._detect_work_type(page_text)
        if not job.get('job_type'):
            job['job_type'] = self.detect_job_type(page_text)
        if not job.get('salary'):
            job['salary'] = self.detect_salary(page_text)

        return job
