import json
import re
import logging
import psycopg2
import psycopg2.extras
from config import Config

logger = logging.getLogger(__name__)


def get_db():
    conn = psycopg2.connect(Config.DATABASE_URL)
    return conn


def _fetchone(conn, query, params=None):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params or ())
        return cur.fetchone()


def _fetchall(conn, query, params=None):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params or ())
        return cur.fetchall()


def _execute(conn, query, params=None):
    with conn.cursor() as cur:
        cur.execute(query, params or ())
    conn.commit()


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT,
            location TEXT,
            url TEXT UNIQUE NOT NULL,
            salary TEXT,
            work_type TEXT,
            job_type TEXT,
            description TEXT,
            source TEXT NOT NULL,
            date_posted TEXT,
            date_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            emailed BOOLEAN DEFAULT FALSE,
            favorite BOOLEAN DEFAULT FALSE,
            hidden BOOLEAN DEFAULT FALSE
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS search_keywords (
            id SERIAL PRIMARY KEY,
            keyword TEXT NOT NULL UNIQUE,
            active BOOLEAN DEFAULT TRUE
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS custom_boards (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            base_url TEXT NOT NULL,
            search_url_template TEXT,
            selectors TEXT,
            active BOOLEAN DEFAULT TRUE
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # Insert default keywords
    default_keywords = [
        "gestionnaire medias sociaux",
        "social media manager",
        "community manager",
        "coordonnateur medias sociaux",
        "coordonnatrice medias sociaux",
        "specialiste medias sociaux",
        "stratege numerique",
        "stratege medias sociaux",
        "chargee de communication",
        "charge de communication",
        "marketing numerique",
        "digital marketing",
        "gestionnaire de contenu",
        "content manager",
        "coordonnateur marketing",
        "coordonnatrice marketing",
        "specialiste e-commerce",
        "responsable communication digitale",
        "social media coordinator",
        "marketing coordinator",
        "brand manager",
        "gestionnaire de marque",
    ]
    for kw in default_keywords:
        cur.execute(
            'INSERT INTO search_keywords (keyword) VALUES (%s) ON CONFLICT (keyword) DO NOTHING', (kw,)
        )

    # Insert default settings
    default_settings = {
        'work_types': json.dumps(['teletravail', 'hybride']),
        'locations': json.dumps(['Montreal', 'Grand Montreal', 'Laval', 'Longueuil', 'Brossard']),
        'salary_min': '50000',
        'salary_max': '60000',
        'job_types': json.dumps(['temps_plein']),
        'date_range_days': '30',
        'email_enabled': '1',
        'email_hour': '8',
        'email_minute': '0',
    }
    for key, value in default_settings.items():
        cur.execute(
            'INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING', (key, value)
        )

    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_db()
    row = _fetchone(conn, 'SELECT value FROM settings WHERE key = %s', (key,))
    conn.close()
    return row['value'] if row else default


def set_setting(key, value):
    conn = get_db()
    _execute(conn, '''
        INSERT INTO settings (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    ''', (key, str(value)))
    conn.close()


def get_active_keywords():
    conn = get_db()
    rows = _fetchall(conn, 'SELECT keyword FROM search_keywords WHERE active = TRUE')
    conn.close()
    return [row['keyword'] for row in rows]


def _normalize(text):
    if not text:
        return ''
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9àâäéèêëïîôùûüçœæ\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def is_duplicate(job_data):
    title = _normalize(job_data.get('title', ''))
    company = _normalize(job_data.get('company', ''))
    if not title:
        return False

    conn = get_db()
    # Check by URL
    row = _fetchone(conn, 'SELECT id FROM jobs WHERE url = %s', (job_data['url'],))
    if row:
        conn.close()
        return True

    # Check by normalized title + company
    if company:
        rows = _fetchall(conn, 'SELECT title, company FROM jobs')
        for r in rows:
            if _normalize(r['title']) == title and _normalize(r['company']) == company:
                conn.close()
                return True
    else:
        if len(title) > 20:
            rows = _fetchall(conn, 'SELECT title FROM jobs')
            for r in rows:
                if _normalize(r['title']) == title:
                    conn.close()
                    return True

    conn.close()
    return False


def insert_job(job_data):
    if is_duplicate(job_data):
        return False

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO jobs
                (title, company, location, url, salary, work_type, job_type,
                 description, source, date_posted)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO NOTHING
            ''', (
                job_data.get('title'),
                job_data.get('company'),
                job_data.get('location'),
                job_data['url'],
                job_data.get('salary'),
                job_data.get('work_type'),
                job_data.get('job_type'),
                job_data.get('description'),
                job_data['source'],
                job_data.get('date_posted'),
            ))
        conn.commit()
        return cur.rowcount > 0
    except psycopg2.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_unemailed_jobs():
    conn = get_db()
    rows = _fetchall(conn,
        'SELECT * FROM jobs WHERE emailed = FALSE AND hidden = FALSE ORDER BY date_scraped DESC'
    )
    conn.close()
    return rows


def mark_jobs_emailed(job_ids):
    if not job_ids:
        return
    conn = get_db()
    placeholders = ','.join(['%s'] * len(job_ids))
    _execute(conn,
        f'UPDATE jobs SET emailed = TRUE WHERE id IN ({placeholders})', tuple(job_ids)
    )
    conn.close()


def get_all_jobs(page=1, per_page=20, source=None, favorite_only=False, show_hidden=False):
    conn = get_db()
    query = 'SELECT * FROM jobs WHERE TRUE'
    params = []

    if not show_hidden:
        query += ' AND hidden = FALSE'
    if source:
        query += ' AND source = %s'
        params.append(source)
    if favorite_only:
        query += ' AND favorite = TRUE'

    query += ' ORDER BY date_scraped DESC LIMIT %s OFFSET %s'
    params.extend([per_page, (page - 1) * per_page])

    rows = _fetchall(conn, query, params)

    count_query = 'SELECT COUNT(*) as total FROM jobs WHERE TRUE'
    count_params = []
    if not show_hidden:
        count_query += ' AND hidden = FALSE'
    if source:
        count_query += ' AND source = %s'
        count_params.append(source)
    if favorite_only:
        count_query += ' AND favorite = TRUE'

    total = _fetchone(conn, count_query, count_params)['total']
    conn.close()
    return rows, total


def toggle_favorite(job_id):
    conn = get_db()
    _execute(conn, 'UPDATE jobs SET favorite = NOT favorite WHERE id = %s', (job_id,))
    conn.close()


def toggle_hidden(job_id):
    conn = get_db()
    _execute(conn, 'UPDATE jobs SET hidden = NOT hidden WHERE id = %s', (job_id,))
    conn.close()


def get_job_stats():
    conn = get_db()
    stats = {}
    stats['total'] = _fetchone(conn, 'SELECT COUNT(*) as c FROM jobs')['c']
    stats['today'] = _fetchone(conn,
        "SELECT COUNT(*) as c FROM jobs WHERE date_scraped::date = CURRENT_DATE"
    )['c']
    stats['favorites'] = _fetchone(conn,
        'SELECT COUNT(*) as c FROM jobs WHERE favorite = TRUE'
    )['c']
    stats['sources'] = {}
    for row in _fetchall(conn,
        'SELECT source, COUNT(*) as c FROM jobs GROUP BY source'
    ):
        stats['sources'][row['source']] = row['c']
    conn.close()
    return stats
