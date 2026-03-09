#!/usr/bin/env python3
"""
Standalone scraping script for GitHub Actions.
Connects directly to the Render PostgreSQL DB and inserts new jobs.
Runs all scrapers in PARALLEL for speed.
"""
import os
import sys
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set DATABASE_URL from environment (GitHub Actions secret)
# Render's external DB URL uses 'postgres://' but psycopg2 needs 'postgresql://'
db_url = os.environ.get('DATABASE_URL', '')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
    os.environ['DATABASE_URL'] = db_url

if not db_url:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

# Minimal delays for GitHub Actions (fresh IP each run, no need to be cautious)
os.environ.setdefault('SCRAPE_DELAY_MIN', '0.5')
os.environ.setdefault('SCRAPE_DELAY_MAX', '1')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

from database import get_active_keywords, insert_job, is_duplicate, init_db
from scrapers.base import extract_highlights
from scrapers import ALL_SCRAPERS

MAX_ENRICH_PER_SOURCE = 15  # Keep enrichment fast


def run_single_scraper(ScraperClass, keywords):
    """Run one scraper and return (name, new_jobs_list)."""
    name = ScraperClass.SOURCE_NAME
    try:
        logger.info(f"[{name}] Démarrage...")
        scraper = ScraperClass()
        jobs = scraper.scrape(keywords)
        logger.info(f"[{name}] {len(jobs)} offres trouvées")

        # Filter duplicates
        new_jobs = [j for j in jobs if not is_duplicate(j)]
        logger.info(f"[{name}] {len(new_jobs)} nouvelles (non-doublons)")

        # Enrich (limited for speed)
        if new_jobs and hasattr(scraper, 'enrich_jobs_batch'):
            new_jobs = scraper.enrich_jobs_batch(new_jobs, max_jobs=MAX_ENRICH_PER_SOURCE)

        # Add highlights
        for job in new_jobs:
            if not job.get('highlights'):
                text = ' '.join(filter(None, [
                    job.get('title', ''),
                    job.get('description', ''),
                ]))
                if text.strip():
                    job['highlights'] = extract_highlights(text)

        return name, new_jobs
    except Exception as e:
        logger.error(f"[{name}] Erreur: {e}", exc_info=True)
        return name, []


def main():
    start_time = time.time()
    logger.info("=== Scrape Job - GitHub Actions (parallel) ===")

    # Ensure DB tables exist
    init_db()

    keywords = get_active_keywords()
    if not keywords:
        logger.warning("Aucun mot-clé actif dans la DB. Rien à scraper.")
        return

    # Cap keywords for speed
    MAX_KEYWORDS = 10
    if len(keywords) > MAX_KEYWORDS:
        logger.info(f"Trop de mots-clés ({len(keywords)}), limité à {MAX_KEYWORDS}")
        keywords = keywords[:MAX_KEYWORDS]

    logger.info(f"Mots-clés ({len(keywords)}): {keywords}")
    logger.info(f"Sources ({len(ALL_SCRAPERS)}): {[s.SOURCE_NAME for s in ALL_SCRAPERS]}")

    # Run ALL scrapers in parallel
    total_new = 0
    with ThreadPoolExecutor(max_workers=len(ALL_SCRAPERS)) as pool:
        futures = {
            pool.submit(run_single_scraper, sc, keywords): sc.SOURCE_NAME
            for sc in ALL_SCRAPERS
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                name, new_jobs = future.result()

                # Insert into DB (sequential to avoid connection conflicts)
                count = 0
                for job in new_jobs:
                    if insert_job(job):
                        count += 1
                        total_new += 1

                logger.info(f"--- {name}: {count} ajoutées ---")
            except Exception as e:
                logger.error(f"[{name}] Erreur insertion: {e}")

    elapsed = time.time() - start_time
    logger.info(f"=== Terminé en {elapsed:.0f}s. {total_new} nouvelle(s) offre(s). ===")


if __name__ == '__main__':
    main()
