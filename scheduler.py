import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from database import get_active_keywords, insert_job, get_setting, is_duplicate
from scrapers import ALL_SCRAPERS
from scrapers.base import extract_highlights
from email_service import send_daily_digest

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone=pytz.timezone('America/Toronto'))

# Max detail pages per source (parallel fetching makes this fast)
MAX_ENRICH_PER_SOURCE = 100


def run_all_scrapers(max_keywords=None):
    logger.info("Demarrage du scraping...")
    keywords = get_active_keywords()
    if not keywords:
        logger.warning("Aucun mot-cle actif.")
        return 0

    if max_keywords:
        keywords = keywords[:max_keywords]
        logger.info(f"Limite a {max_keywords} mots-cles: {keywords}")

    total_new = 0
    for ScraperClass in ALL_SCRAPERS:
        try:
            logger.info(f"--- Demarrage {ScraperClass.SOURCE_NAME} ---")
            scraper = ScraperClass()
            jobs = scraper.scrape(keywords)
            logger.info(f"[{ScraperClass.SOURCE_NAME}] {len(jobs)} offres trouvees")

            # Filter out duplicates first (don't waste time enriching them)
            new_jobs = [j for j in jobs if not is_duplicate(j)]
            logger.info(f"[{ScraperClass.SOURCE_NAME}] {len(new_jobs)} nouvelles (non-doublons)")

            # Batch enrich all new jobs in parallel
            if new_jobs and hasattr(scraper, 'enrich_jobs_batch'):
                new_jobs = scraper.enrich_jobs_batch(new_jobs, max_jobs=MAX_ENRICH_PER_SOURCE)

            # Insert enriched jobs
            new_for_source = 0
            for job in new_jobs:
                # Extract highlights if not already done
                if not job.get('highlights'):
                    text = ' '.join(filter(None, [
                        job.get('title', ''),
                        job.get('description', ''),
                    ]))
                    if text.strip():
                        job['highlights'] = extract_highlights(text)

                if insert_job(job):
                    new_for_source += 1
                    total_new += 1

            logger.info(f"--- {ScraperClass.SOURCE_NAME}: {new_for_source} ajoutees ---")
        except Exception as e:
            logger.error(f"Erreur scraper {ScraperClass.SOURCE_NAME}: {e}", exc_info=True)
            continue

    logger.info(f"Scraping termine. {total_new} nouvelle(s) offre(s) ajoutee(s).")
    return total_new


def init_scheduler():
    scheduler.add_job(
        run_all_scrapers,
        CronTrigger(hour='6,12,18,0', timezone=pytz.timezone('America/Toronto')),
        id='scrape_jobs',
        replace_existing=True,
    )

    email_hour = int(get_setting('email_hour', '8'))
    email_minute = int(get_setting('email_minute', '0'))
    scheduler.add_job(
        send_daily_digest,
        CronTrigger(
            hour=email_hour,
            minute=email_minute,
            timezone=pytz.timezone('America/Toronto'),
        ),
        id='email_digest',
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Planificateur demarre.")
