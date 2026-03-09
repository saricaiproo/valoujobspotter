from scrapers.linkedin import LinkedInScraper
from scrapers.jobillico import JobillicoScraper
from scrapers.adzuna import AdzunaScraper
from scrapers.remoteok import RemoteOKScraper
from scrapers.guichet_emplois import GuichetEmploisScraper
from scrapers.indeed import IndeedScraper
from scrapers.emploi_quebec import EmploiQuebecScraper
from scrapers.isarta import IsartaScraper
from scrapers.grenier import GrenierScraper

ALL_SCRAPERS = [
    LinkedInScraper,         # Works - major job board
    JobillicoScraper,        # Works - Quebec-focused
    IndeedScraper,           # Indeed Canada - HTML+JSON with cloudscraper
    EmploiQuebecScraper,     # Emploi Québec - clean public API
    IsartaScraper,           # Isarta - Quebec marketing/comms jobs
    GrenierScraper,          # Grenier aux emplois - Quebec creative/marketing
    AdzunaScraper,           # API-based aggregator
    GuichetEmploisScraper,   # Government of Canada job board (fixed selectors)
    RemoteOKScraper,         # Remote jobs (all teletravail)
]

# Source priority for dedup: lower number = higher priority
SOURCE_PRIORITY = {
    'LinkedIn': 1,
    'Indeed': 2,
    'Jobillico': 3,
    'Isarta': 4,
    'Grenier': 5,
    'Emploi-Québec': 6,
    'Guichet-Emplois': 7,
    'Adzuna': 8,
    'RemoteOK': 9,
}
