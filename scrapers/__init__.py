from scrapers.jobillico import JobillicoScraper
from scrapers.jobboom import JobboomScraper
from scrapers.linkedin import LinkedInScraper
from scrapers.adzuna import AdzunaScraper
from scrapers.glassdoor import GlassdoorScraper

ALL_SCRAPERS = [
    LinkedInScraper,     # Works - public search
    JobillicoScraper,    # Works - scraper-friendly
    JobboomScraper,      # Testing new URL
    AdzunaScraper,       # Job aggregator
    GlassdoorScraper,    # Public listings
]
