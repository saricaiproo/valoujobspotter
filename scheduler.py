import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from database import get_active_keywords, insert_job, get_setting
from scrapers import ALL_SCRAPERS
from scrapers.base import extract_highlights
from email_service import send_daily_digest

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone=pytz.timezone('America/Toronto'))

# Max detail pages to fetch per scraper (to avoid timeout)
MAX_DETAIL_PAGES = 8


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

            # Enrich jobs with detail pages (only for scrapers that support it)
            enriched = 0
            for job in jobs:
                # Only enrich if missing key info and scraper supports it
                if (enriched < MAX_DETAIL_PAGES
                        and hasattr(scraper, 'enrich_job')
                        and _needs_enrichment(job)):
                    try:
                        job = scraper.enrich_job(job)
                        enriched += 1
                    except Exception as e:
                        logger.debug(f"Enrichissement echoue: {e}")

                # Extract highlights from whatever description we have
                if not job.get('highlights') and job.get('description'):
                    job['highlights'] = extract_highlights(
                        job.get('title', '') + ' ' + job.get('description', '')
                    )

                if insert_job(job):
                    total_new += 1

            logger.info(f"--- {ScraperClass.SOURCE_NAME}: {total_new} nouvelles, {enriched} enrichies ---")
        except Exception as e:
            logger.error(f"Erreur scraper {ScraperClass.SOURCE_NAME}: {e}", exc_info=True)
            continue

    logger.info(f"Scraping termine. {total_new} nouvelle(s) offre(s) ajoutee(s).")
    return total_new


def _needs_enrichment(job):
    """Check if job is missing key info that detail page could fill."""
    missing = 0
    if not job.get('description'):
        missing += 1
    if not job.get('salary'):
        missing += 1
    if not job.get('work_type'):
        missing += 1
    if not job.get('job_type'):
        missing += 1
    return missing >= 2  # enrich if missing 2+ fields


def init_scheduler():
    # Scrape every 6 hours
    scheduler.add_job(
        run_all_scrapers,
        CronTrigger(hour='6,12,18,0', timezone=pytz.timezone('America/Toronto')),
        id='scrape_jobs',
        replace_existing=True,
    )

    # Send email digest at 8 AM Montreal time
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
