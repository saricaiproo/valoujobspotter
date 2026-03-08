from scrapers.indeed import IndeedScraper
from scrapers.jobillico import JobillicoScraper
from scrapers.jobboom import JobboomScraper
from scrapers.linkedin import LinkedInScraper
from scrapers.adzuna import AdzunaScraper
from scrapers.glassdoor import GlassdoorScraper

ALL_SCRAPERS = [
    JobillicoScraper,    # Most scraper-friendly
    JobboomScraper,      # Scraper-friendly
    AdzunaScraper,       # Public search, rarely blocks
    GlassdoorScraper,    # Public listings
    IndeedScraper,       # RSS feed (less blocking)
    LinkedInScraper,     # Public search (may block)
]
