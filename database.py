import sqlite3
import json
from datetime import datetime
from config import Config


def get_db():
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            date_scraped DATETIME DEFAULT CURRENT_TIMESTAMP,
            emailed INTEGER DEFAULT 0,
            favorite INTEGER DEFAULT 0,
            hidden INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS search_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL UNIQUE,
            active INTEGER DEFAULT 1
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            base_url TEXT NOT NULL,
            search_url_template TEXT,
            selectors TEXT,
            active INTEGER DEFAULT 1
        )
    ''')

    cursor.execute('''
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
        cursor.execute(
            'INSERT OR IGNORE INTO search_keywords (keyword) VALUES (?)', (kw,)
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
        cursor.execute(
            'INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value)
        )

    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
        (key, str(value))
    )
    conn.commit()
    conn.close()


def get_active_keywords():
    conn = get_db()
    rows = conn.execute(
        'SELECT keyword FROM search_keywords WHERE active = 1'
    ).fetchall()
    conn.close()
    return [row['keyword'] for row in rows]


def _normalize(text):
    """Normalize text for dedup comparison."""
    if not text:
        return ''
    import re
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9àâäéèêëïîôùûüçœæ\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def is_duplicate(job_data):
    """Check if a job with similar title + company already exists."""
    title = _normalize(job_data.get('title', ''))
    company = _normalize(job_data.get('company', ''))
    if not title:
        return False

    conn = get_db()
    # Check by URL first (exact match)
    row = conn.execute('SELECT id FROM jobs WHERE url = ?', (job_data['url'],)).fetchone()
    if row:
        conn.close()
        return True

    # Check by normalized title + company (fuzzy dedup across sources)
    if company:
        rows = conn.execute('SELECT title, company FROM jobs').fetchall()
        for r in rows:
            if _normalize(r['title']) == title and _normalize(r['company']) == company:
                conn.close()
                return True
    else:
        # No company info — match on title alone only if very specific
        if len(title) > 20:
            rows = conn.execute('SELECT title FROM jobs').fetchall()
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
        conn.execute('''
            INSERT OR IGNORE INTO jobs
            (title, company, location, url, salary, work_type, job_type,
             description, source, date_posted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        return conn.total_changes > 0
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_unemailed_jobs():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM jobs WHERE emailed = 0 AND hidden = 0 ORDER BY date_scraped DESC'
    ).fetchall()
    conn.close()
    return rows


def mark_jobs_emailed(job_ids):
    if not job_ids:
        return
    conn = get_db()
    placeholders = ','.join('?' * len(job_ids))
    conn.execute(
        f'UPDATE jobs SET emailed = 1 WHERE id IN ({placeholders})', job_ids
    )
    conn.commit()
    conn.close()


def get_all_jobs(page=1, per_page=20, source=None, favorite_only=False, show_hidden=False):
    conn = get_db()
    query = 'SELECT * FROM jobs WHERE 1=1'
    params = []

    if not show_hidden:
        query += ' AND hidden = 0'
    if source:
        query += ' AND source = ?'
        params.append(source)
    if favorite_only:
        query += ' AND favorite = 1'

    query += ' ORDER BY date_scraped DESC LIMIT ? OFFSET ?'
    params.extend([per_page, (page - 1) * per_page])

    rows = conn.execute(query, params).fetchall()

    count_query = 'SELECT COUNT(*) as total FROM jobs WHERE 1=1'
    count_params = []
    if not show_hidden:
        count_query += ' AND hidden = 0'
    if source:
        count_query += ' AND source = ?'
        count_params.append(source)
    if favorite_only:
        count_query += ' AND favorite = 1'

    total = conn.execute(count_query, count_params).fetchone()['total']
    conn.close()
    return rows, total


def toggle_favorite(job_id):
    conn = get_db()
    conn.execute('UPDATE jobs SET favorite = NOT favorite WHERE id = ?', (job_id,))
    conn.commit()
    conn.close()


def toggle_hidden(job_id):
    conn = get_db()
    conn.execute('UPDATE jobs SET hidden = NOT hidden WHERE id = ?', (job_id,))
    conn.commit()
    conn.close()


def get_job_stats():
    conn = get_db()
    stats = {}
    stats['total'] = conn.execute('SELECT COUNT(*) as c FROM jobs').fetchone()['c']
    stats['today'] = conn.execute(
        "SELECT COUNT(*) as c FROM jobs WHERE date(date_scraped) = date('now')"
    ).fetchone()['c']
    stats['favorites'] = conn.execute(
        'SELECT COUNT(*) as c FROM jobs WHERE favorite = 1'
    ).fetchone()['c']
    stats['sources'] = {}
    for row in conn.execute(
        'SELECT source, COUNT(*) as c FROM jobs GROUP BY source'
    ).fetchall():
        stats['sources'][row['source']] = row['c']
    conn.close()
    return stats
