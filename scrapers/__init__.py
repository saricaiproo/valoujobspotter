from scrapers.linkedin import LinkedInScraper
from scrapers.jobillico import JobillicoScraper
from scrapers.adzuna import AdzunaScraper
from scrapers.remoteok import RemoteOKScraper
from scrapers.guichet_emplois import GuichetEmploisScraper
from scrapers.google_jobs import GoogleJobsScraper
from scrapers.indeed import IndeedScraper
from scrapers.emploi_quebec import EmploiQuebecScraper

ALL_SCRAPERS = [
    LinkedInScraper,         # Works - major job board
    JobillicoScraper,        # Works - Quebec-focused
    IndeedScraper,           # Indeed Canada - HTML+JSON with cloudscraper
    EmploiQuebecScraper,     # Emploi Québec - clean public API
    AdzunaScraper,           # API-based aggregator
    GuichetEmploisScraper,   # Government of Canada job board
    RemoteOKScraper,         # Remote jobs (all teletravail)
    GoogleJobsScraper,       # Google Jobs - lowest priority (dedup prefers original sources)
]

# Source priority for dedup: lower number = higher priority
# If same job found on LinkedIn AND Google Jobs, keep the LinkedIn one
SOURCE_PRIORITY = {
    'LinkedIn': 1,
    'Indeed': 2,
    'Jobillico': 3,
    'Emploi-Québec': 4,
    'Guichet-Emplois': 5,
    'Adzuna': 6,
    'RemoteOK': 7,
    'Google Jobs': 10,  # Lowest priority - aggregator
}
