import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from database import get_active_keywords, insert_job, get_setting
from scrapers import ALL_SCRAPERS
from email_service import send_daily_digest

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone=pytz.timezone('America/Toronto'))


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
            new_for_source = 0
            for job in jobs:
                if insert_job(job):
                    new_for_source += 1
                    total_new += 1
            logger.info(f"--- {ScraperClass.SOURCE_NAME}: {new_for_source} nouvelles offres ---")
        except Exception as e:
            logger.error(f"Erreur scraper {ScraperClass.SOURCE_NAME}: {e}", exc_info=True)
            continue

    logger.info(f"Scraping termine. {total_new} nouvelle(s) offre(s) ajoutee(s).")
    return total_new


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
