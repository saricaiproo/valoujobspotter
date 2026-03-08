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

# Max detail pages to fetch per scraper per keyword
# With 1-2s delay each, 15 pages = ~30s extra per source = manageable
MAX_DETAIL_PER_SOURCE = 15


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
            logger.info(f"[{ScraperClass.SOURCE_NAME}] {len(jobs)} offres trouvees au total")

            # First pass: filter out duplicates to avoid wasting time enriching them
            new_jobs = []
            for job in jobs:
                if not is_duplicate(job):
                    new_jobs.append(job)

            logger.info(f"[{ScraperClass.SOURCE_NAME}] {len(new_jobs)} nouvelles (non-doublons)")

            # Second pass: enrich new jobs with detail pages
            enriched = 0
            new_for_source = 0
            for job in new_jobs:
                # Enrich if scraper supports it and we haven't hit the limit
                if (enriched < MAX_DETAIL_PER_SOURCE
                        and hasattr(scraper, 'enrich_job')
                        and _needs_enrichment(job)):
                    try:
                        job = scraper.enrich_job(job)
                        enriched += 1
                        logger.info(f"  Enrichi: {job.get('title', '')[:50]} | "
                                    f"mode={job.get('work_type', '?')} "
                                    f"type={job.get('job_type', '?')} "
                                    f"sal={bool(job.get('salary'))}")
                    except Exception as e:
                        logger.debug(f"Enrichissement echoue: {e}")

                # Extract highlights from whatever text we have
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

            logger.info(f"--- {ScraperClass.SOURCE_NAME}: {new_for_source} ajoutees, {enriched} enrichies ---")
        except Exception as e:
            logger.error(f"Erreur scraper {ScraperClass.SOURCE_NAME}: {e}", exc_info=True)
            continue

    logger.info(f"Scraping termine. {total_new} nouvelle(s) offre(s) ajoutee(s).")
    return total_new


def _needs_enrichment(job):
    """Check if job is missing key info that detail page could fill."""
    if not job.get('description'):
        return True
    if not job.get('work_type'):
        return True
    if not job.get('job_type'):
        return True
    if not job.get('salary'):
        return True
    return False


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
