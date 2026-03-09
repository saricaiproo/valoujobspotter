#!/usr/bin/env python3
"""
Standalone scraping script for GitHub Actions.
Connects directly to the Render PostgreSQL DB and inserts new jobs.
No Flask dependency needed.
"""
import os
import sys
import logging

# Set DATABASE_URL from environment (GitHub Actions secret)
# Render's external DB URL uses 'postgres://' but psycopg2 needs 'postgresql://'
db_url = os.environ.get('DATABASE_URL', '')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
    os.environ['DATABASE_URL'] = db_url

if not db_url:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

# Faster delays for GitHub Actions (no need to be as cautious)
os.environ.setdefault('SCRAPE_DELAY_MIN', '1')
os.environ.setdefault('SCRAPE_DELAY_MAX', '2')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

from database import get_active_keywords, insert_job, is_duplicate, init_db
from scrapers.base import extract_highlights

# Only import the scrapers that actually work
from scrapers.linkedin import LinkedInScraper
from scrapers.jobillico import JobillicoScraper
from scrapers.adzuna import AdzunaScraper
from scrapers.indeed import IndeedScraper
from scrapers.emploi_quebec import EmploiQuebecScraper

ACTIVE_SCRAPERS = [
    LinkedInScraper,
    JobillicoScraper,
    AdzunaScraper,
    IndeedScraper,
    EmploiQuebecScraper,
]

MAX_ENRICH_PER_SOURCE = 30


def main():
    logger.info("=== Scrape Job - GitHub Actions ===")

    # Ensure DB tables exist
    init_db()

    keywords = get_active_keywords()
    if not keywords:
        logger.warning("Aucun mot-clé actif dans la DB. Rien à scraper.")
        return

    # Cap keywords to keep scrape time under 20 minutes
    MAX_KEYWORDS = 10
    if len(keywords) > MAX_KEYWORDS:
        logger.info(f"Trop de mots-clés ({len(keywords)}), limité à {MAX_KEYWORDS}")
        keywords = keywords[:MAX_KEYWORDS]

    logger.info(f"Mots-clés actifs ({len(keywords)}): {keywords}")

    total_new = 0
    for ScraperClass in ACTIVE_SCRAPERS:
        try:
            name = ScraperClass.SOURCE_NAME
            logger.info(f"--- {name} ---")
            scraper = ScraperClass()
            jobs = scraper.scrape(keywords)
            logger.info(f"[{name}] {len(jobs)} offres trouvées")

            # Filter duplicates
            new_jobs = [j for j in jobs if not is_duplicate(j)]
            logger.info(f"[{name}] {len(new_jobs)} nouvelles (non-doublons)")

            # Enrich
            if new_jobs and hasattr(scraper, 'enrich_jobs_batch'):
                new_jobs = scraper.enrich_jobs_batch(new_jobs, max_jobs=MAX_ENRICH_PER_SOURCE)

            # Insert
            count = 0
            for job in new_jobs:
                if not job.get('highlights'):
                    text = ' '.join(filter(None, [
                        job.get('title', ''),
                        job.get('description', ''),
                    ]))
                    if text.strip():
                        job['highlights'] = extract_highlights(text)

                if insert_job(job):
                    count += 1
                    total_new += 1

            logger.info(f"--- {name}: {count} ajoutées ---")

        except Exception as e:
            logger.error(f"Erreur {ScraperClass.SOURCE_NAME}: {e}", exc_info=True)
            continue

    logger.info(f"=== Terminé. {total_new} nouvelle(s) offre(s) ajoutée(s). ===")


if __name__ == '__main__':
    main()
