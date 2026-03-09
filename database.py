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
        if params is None:
            cur.execute(query)
        else:
            cur.execute(query, params)
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
            hidden BOOLEAN DEFAULT FALSE,
            highlights TEXT DEFAULT '[]',
            applied BOOLEAN DEFAULT FALSE,
            applied_at TIMESTAMP
        )
    ''')

    # Add highlights column if it doesn't exist (migration for existing DBs)
    try:
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS highlights TEXT DEFAULT '[]'")
    except Exception:
        conn.rollback()

    # Add parsed date column for proper sorting by publication date
    try:
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS date_published TIMESTAMP")
    except Exception:
        conn.rollback()

    # Add applied tracking columns
    try:
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS applied BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS applied_at TIMESTAMP")
    except Exception:
        conn.rollback()

    # Backfill date_published from date_posted text
    try:
        cur.execute("""
            UPDATE jobs SET date_published = date_posted::timestamp
            WHERE date_published IS NULL AND date_posted IS NOT NULL AND date_posted != ''
            AND date_posted ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        """)
        conn.commit()
    except Exception:
        conn.rollback()

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

    # Insert default keywords — kept lean for speed
    # Each keyword runs across all scrapers with pagination, so fewer = faster
    # The relevance filter catches variations we don't need as explicit keywords
    default_keywords = [
        "social media",
        "community manager",
        "coordonnateur marketing",
        "médias sociaux",
        "marketing numérique",
        "chargé de communication",
        "gestionnaire de contenu",
        "content manager",
        "marketing coordinator",
        "brand manager",
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
    """Check if job already exists. Returns True if duplicate and should be skipped.

    Source priority: if same job exists from a higher-priority source, skip.
    If same job exists from a lower-priority source, also skip (keep original).
    """
    from scrapers import SOURCE_PRIORITY

    title = _normalize(job_data.get('title', ''))
    company = _normalize(job_data.get('company', ''))
    source = job_data.get('source', '')
    if not title:
        return False

    conn = get_db()
    # Check by URL
    row = _fetchone(conn, 'SELECT id FROM jobs WHERE url = %s', (job_data['url'],))
    if row:
        conn.close()
        return True

    # Check by normalized title + company (cross-source dedup)
    if company:
        rows = _fetchall(conn, 'SELECT title, company, source FROM jobs')
        for r in rows:
            if _normalize(r['title']) == title and _normalize(r['company']) == company:
                # Same job exists from another source
                existing_priority = SOURCE_PRIORITY.get(r['source'], 50)
                new_priority = SOURCE_PRIORITY.get(source, 50)
                if new_priority <= existing_priority:
                    # New source is higher priority - replace existing
                    _execute(conn, 'DELETE FROM jobs WHERE title = %s AND company = %s AND source = %s',
                             (r['title'], r['company'], r['source']))
                    conn.close()
                    return False  # Not a duplicate - insert the better one
                else:
                    # Existing source is higher priority - skip new one
                    conn.close()
                    return True
    else:
        if len(title) > 20:
            rows = _fetchall(conn, 'SELECT title, source FROM jobs')
            for r in rows:
                if _normalize(r['title']) == title:
                    conn.close()
                    return True

    conn.close()
    return False


def is_relevant(job_data):
    """Filter out jobs that don't match the target roles."""
    title = (job_data.get('title', '') + ' ' + job_data.get('description', '')).lower()
    job_title = job_data.get('title', '').lower()

    # Compound reject patterns — checked FIRST, override relevant terms
    # These catch cases like "Social Worker" where "social" alone would match
    reject_compound = [
        'social worker', 'travailleur social', 'travailleuse sociale',
        'service social', 'aide social', 'work social',
        'psychologue', 'psychologist', 'therapist', 'thérapeute',
        'educateur specialise', 'éducateur spécialisé', 'éducatrice spécialisée',
        'intervenant', 'intervenante', 'prepose', 'préposé', 'préposée',
        'technicien comptable', 'technical support', 'support technique',
        'agent de securite', 'security agent', 'gardien',
        'commis', 'caissier', 'caissière', 'cashier',
        'receptionniste', 'réceptionniste', 'receptionist',
        'livreur', 'delivery driver', 'warehouse', 'entrepot',
        'manutentionnaire', 'journalier', 'manoeuvre',
        'enseignant', 'enseignante', 'teacher', 'professeur',
        'technicien informatique', 'it technician',
        'analyste financier', 'financial analyst',
        'agent immobilier', 'real estate agent',
        'représentant des ventes', 'sales representative',
    ]

    for term in reject_compound:
        if term in job_title:
            return False

    # Reject if title contains these (clearly wrong field)
    reject_terms = [
        'développeur', 'developpeur', 'developer', 'ingénieur',
        'ingenieur', 'engineer', 'game', 'jeu', 'jeux',
        'infirmier', 'infirmière', 'nurse', 'médecin', 'mecanic',
        'mécanicien', 'mecanicien', 'soudeur', 'welder', 'plumber',
        'plombier', 'électricien', 'electricien', 'comptable',
        'accountant', 'avocat', 'lawyer', 'chauffeur', 'driver',
        'cuisinier', 'chef cuisinier', 'cook', 'serveur', 'serveuse',
        'concierge', 'janitor', 'data scientist', 'data engineer',
        'devops', 'sysadmin', 'backend', 'frontend', 'full stack',
        'fullstack', 'qa tester', 'game test', 'architecte logiciel',
        'software architect', 'machine learning', 'dentist', 'dentiste',
        'pharmacien', 'pharmacist', 'vétérinaire', 'veterinaire',
        'physiotherapeute', 'physiothérapeute', 'orthophoniste',
        'diététiste', 'nutritionniste', 'optométriste',
        'technicien', 'machiniste', 'opérateur', 'operateur',
        'assembleur', 'soudeur', 'peintre industriel',
        'agent de sécurité', 'gardien de sécurité',
    ]

    # Check reject terms (in title only)
    for term in reject_terms:
        if term in job_title:
            return False

    # Must contain at least one relevant term
    relevant_terms = [
        'media', 'médias', 'medias sociaux', 'médias sociaux',
        'social media', 'réseaux sociaux', 'reseaux sociaux',
        'marketing', 'communication', 'contenu', 'content',
        'community manager', 'communauté', 'numerique',
        'numérique', 'digital', 'marque', 'brand', 'coordonn',
        'strateg', 'e-commerce', 'ecommerce', 'redact', 'rédact',
        'seo', 'sem', 'publicite', 'publicité',
        'gestionnaire de communaut', 'relations publiques',
        'public relations', 'influenc', 'copywrit',
        'creation de contenu', 'créateur de contenu', 'création de contenu',
    ]

    # Check if any relevant term is present
    for term in relevant_terms:
        if term in title:
            return True

    return False


def _parse_date_posted(date_str):
    """Try to parse date_posted text into a datetime for proper sorting."""
    if not date_str:
        return None
    from datetime import datetime, timedelta
    s = str(date_str).strip()

    # Handle relative dates like "Il y a 3 jours", "Aujourd'hui", "Hier"
    s_lower = s.lower()
    if "aujourd" in s_lower:
        return datetime.now()
    if s_lower == 'hier' or 'yesterday' in s_lower:
        return datetime.now() - timedelta(days=1)
    # "Il y a X jours/heures/minutes"
    rel_match = re.search(r'il y a\s+(\d+)\s*(jour|heure|minute|semaine|mois)', s_lower)
    if rel_match:
        num = int(rel_match.group(1))
        unit = rel_match.group(2)
        if 'jour' in unit:
            return datetime.now() - timedelta(days=num)
        elif 'heure' in unit:
            return datetime.now() - timedelta(hours=num)
        elif 'minute' in unit:
            return datetime.now() - timedelta(minutes=num)
        elif 'semaine' in unit:
            return datetime.now() - timedelta(weeks=num)
        elif 'mois' in unit:
            return datetime.now() - timedelta(days=num * 30)
    # English relative: "3 days ago"
    rel_match_en = re.search(r'(\d+)\s*(day|hour|minute|week|month)s?\s*ago', s_lower)
    if rel_match_en:
        num = int(rel_match_en.group(1))
        unit = rel_match_en.group(2)
        if 'day' in unit:
            return datetime.now() - timedelta(days=num)
        elif 'hour' in unit:
            return datetime.now() - timedelta(hours=num)
        elif 'week' in unit:
            return datetime.now() - timedelta(weeks=num)
        elif 'month' in unit:
            return datetime.now() - timedelta(days=num * 30)

    # ISO and standard date formats
    for fmt in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(s[:26], fmt)
        except (ValueError, IndexError):
            continue
    # Try just the date part if there's a T
    if 'T' in s:
        try:
            return datetime.strptime(s[:10], '%Y-%m-%d')
        except (ValueError, IndexError):
            pass
    return None


def insert_job(job_data):
    if not is_relevant(job_data):
        return False
    if is_duplicate(job_data):
        return False

    conn = get_db()
    try:
        highlights = json.dumps(job_data.get('highlights', []))
        date_published = _parse_date_posted(job_data.get('date_posted'))
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO jobs
                (title, company, location, url, salary, work_type, job_type,
                 description, source, date_posted, highlights, date_published)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                highlights,
                date_published,
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


def _build_condition_filters():
    """Build SQL filter clauses from user's saved conditions."""
    clauses = []
    params = []

    work_types = json.loads(get_setting('work_types', '[]'))
    job_types = json.loads(get_setting('job_types', '[]'))
    show_unknown = get_setting('show_unknown', '1') == '1'

    # Work type filter
    if work_types:
        wt_placeholders = ','.join(['%s'] * len(work_types))
        if show_unknown:
            clauses.append(f"(work_type IN ({wt_placeholders}) OR work_type IS NULL OR work_type = '')")
        else:
            clauses.append(f"work_type IN ({wt_placeholders})")
        params.extend(work_types)

    # Job type filter — map setting values to display values
    if job_types:
        type_map = {
            'temps_plein': 'Temps plein',
            'temps_partiel': 'Temps partiel',
            'contrat': 'Contrat',
            'stage': 'Stage',
            'pigiste': 'Pigiste',
        }
        display_types = [type_map.get(jt, jt) for jt in job_types]
        jt_placeholders = ','.join(['%s'] * len(display_types))
        if show_unknown:
            clauses.append(f"(job_type IN ({jt_placeholders}) OR job_type IS NULL OR job_type = '')")
        else:
            clauses.append(f"job_type IN ({jt_placeholders})")
        params.extend(display_types)

    return clauses, params


def get_all_jobs(page=1, per_page=20, source=None, favorite_only=False,
                  show_hidden=False, apply_conditions=True,
                  work_type=None, job_type=None, applied=None,
                  sort='newest', days=None):
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

    # Page-level filters (filter bar on /jobs)
    if work_type:
        query += ' AND work_type = %s'
        params.append(work_type)
    if job_type:
        query += ' AND job_type = %s'
        params.append(job_type)
    if applied == 'yes':
        query += ' AND applied = TRUE'
    elif applied == 'no':
        query += ' AND applied = FALSE'
    if days and days > 0:
        query += " AND COALESCE(date_published, date_scraped) >= CURRENT_TIMESTAMP - INTERVAL '%s days'"
        params.append(days)

    # Apply user conditions from settings
    if apply_conditions:
        cond_clauses, cond_params = _build_condition_filters()
        for clause in cond_clauses:
            query += ' AND ' + clause
        params.extend(cond_params)

    # Sorting — use date_published (actual post date) with date_scraped as fallback
    if sort == 'oldest':
        query += ' ORDER BY COALESCE(date_published, date_scraped) ASC'
    elif sort == 'salary':
        query += ' ORDER BY salary DESC NULLS LAST, COALESCE(date_published, date_scraped) DESC'
    else:
        query += ' ORDER BY COALESCE(date_published, date_scraped) DESC'

    query += ' LIMIT %s OFFSET %s'
    params.extend([per_page, (page - 1) * per_page])

    rows = _fetchall(conn, query, params)

    # Count query (same filters, no sort/limit)
    count_query = 'SELECT COUNT(*) as total FROM jobs WHERE TRUE'
    count_params = []
    if not show_hidden:
        count_query += ' AND hidden = FALSE'
    if source:
        count_query += ' AND source = %s'
        count_params.append(source)
    if favorite_only:
        count_query += ' AND favorite = TRUE'
    if work_type:
        count_query += ' AND work_type = %s'
        count_params.append(work_type)
    if job_type:
        count_query += ' AND job_type = %s'
        count_params.append(job_type)
    if applied == 'yes':
        count_query += ' AND applied = TRUE'
    elif applied == 'no':
        count_query += ' AND applied = FALSE'
    if days and days > 0:
        count_query += " AND COALESCE(date_published, date_scraped) >= CURRENT_TIMESTAMP - INTERVAL '%s days'"
        count_params.append(days)

    if apply_conditions:
        cond_clauses, cond_params = _build_condition_filters()
        for clause in cond_clauses:
            count_query += ' AND ' + clause
        count_params.extend(cond_params)

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


def toggle_applied(job_id):
    conn = get_db()
    job = _fetchone(conn, 'SELECT applied FROM jobs WHERE id = %s', (job_id,))
    if job and job['applied']:
        _execute(conn, 'UPDATE jobs SET applied = FALSE, applied_at = NULL WHERE id = %s', (job_id,))
    else:
        _execute(conn, 'UPDATE jobs SET applied = TRUE, applied_at = CURRENT_TIMESTAMP WHERE id = %s', (job_id,))
    conn.close()


def get_job_stats():
    conn = get_db()
    stats = {}
    stats['total'] = _fetchone(conn, 'SELECT COUNT(*) as c FROM jobs WHERE hidden = FALSE')['c']
    stats['today'] = _fetchone(conn,
        "SELECT COUNT(*) as c FROM jobs WHERE hidden = FALSE AND date_scraped::date = CURRENT_DATE"
    )['c']
    stats['favorites'] = _fetchone(conn,
        'SELECT COUNT(*) as c FROM jobs WHERE favorite = TRUE'
    )['c']
    stats['applied'] = _fetchone(conn,
        'SELECT COUNT(*) as c FROM jobs WHERE applied = TRUE'
    )['c']
    stats['sources'] = {}
    for row in _fetchall(conn,
        'SELECT source, COUNT(*) as c FROM jobs GROUP BY source'
    ):
        stats['sources'][row['source']] = row['c']
    conn.close()
    return stats
