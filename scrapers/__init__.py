from scrapers.jobillico import JobillicoScraper
from scrapers.linkedin import LinkedInScraper
from scrapers.adzuna import AdzunaScraper
from scrapers.glassdoor import GlassdoorScraper

ALL_SCRAPERS = [
    LinkedInScraper,     # Works - 126 jobs found
    JobillicoScraper,    # Works - fixing to get more
    AdzunaScraper,       # Job aggregator
    GlassdoorScraper,    # Public listings
]
