import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp-relay.brevo.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_LOGIN = os.environ.get('SMTP_LOGIN')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
    RECIPIENT_EMAIL = os.environ.get('RECIPIENT_EMAIL', 'valou2244@hotmail.fr')
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'saricaiproo@gmail.com')
    APP_PASSWORD = os.environ.get('APP_PASSWORD')
    DATABASE_PATH = os.environ.get('DATABASE_PATH',
                                     os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jobs.db'))
    TIMEZONE = 'America/Toronto'
    SCRAPE_DELAY_MIN = 2
    SCRAPE_DELAY_MAX = 5
