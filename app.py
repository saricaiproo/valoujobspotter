import json
import logging
import threading
from datetime import datetime, timezone
from functools import wraps
from math import ceil

import bcrypt
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from markupsafe import Markup

from config import Config
from database import (
    init_db, get_db, get_job_stats, get_all_jobs, get_setting, set_setting,
    get_active_keywords, toggle_favorite, toggle_hidden, toggle_applied, _fetchall, _execute,
)
from scheduler import init_scheduler, run_all_scrapers
from email_service import send_daily_digest

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY


# ============================================
# JINJA FILTERS
# ============================================

@app.template_filter('relative_date')
def relative_date_filter(dt):
    """Convert datetime to relative French string like 'Il y a 2 jours'."""
    if not dt:
        return ''
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "A l'instant"
    minutes = seconds // 60
    if minutes < 60:
        return f"Il y a {minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"Il y a {hours}h"
    days = hours // 24
    if days == 1:
        return "Hier"
    if days < 7:
        return f"Il y a {days} jours"
    weeks = days // 7
    if weeks == 1:
        return "Il y a 1 semaine"
    if weeks < 5:
        return f"Il y a {weeks} semaines"
    months = days // 30
    if months == 1:
        return "Il y a 1 mois"
    if months < 12:
        return f"Il y a {months} mois"
    return dt.strftime('%d %b %Y')


@app.template_filter('format_posted_date')
def format_posted_date_filter(value):
    """Format date_posted string to a readable French date."""
    if not value:
        return ''
    s = str(value).strip()
    months_fr = ['', 'jan.', 'fev.', 'mars', 'avr.', 'mai', 'juin',
                 'juil.', 'aout', 'sep.', 'oct.', 'nov.', 'dec.']
    # Try ISO format: 2024-03-15 or 2024-03-15T...
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            dt = datetime.strptime(s[:19], fmt)
            return f"{dt.day} {months_fr[dt.month]} {dt.year}"
        except (ValueError, IndexError):
            continue
    # Fallback: return as-is, truncated
    return s[:20] if len(s) > 20 else s


@app.template_filter('parse_highlights')
def parse_highlights_filter(value):
    """Parse highlights JSON string to list."""
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


@app.template_filter('job_modal_data')
def job_modal_data_filter(job):
    """Serialize job data for the detail modal (HTML-attribute-safe)."""
    import html as html_mod
    highlights = job.get('highlights') or '[]'
    if isinstance(highlights, str):
        try:
            highlights = json.loads(highlights)
        except (json.JSONDecodeError, TypeError):
            highlights = []

    date_posted = job.get('date_posted', '') or ''
    if date_posted:
        date_posted = format_posted_date_filter(date_posted)

    data = {
        'title': job.get('title', '') or '',
        'company': job.get('company', '') or '',
        'location': job.get('location', '') or '',
        'url': job.get('url', '') or '',
        'source': job.get('source', '') or '',
        'work_type': job.get('work_type', '') or '',
        'job_type': job.get('job_type', '') or '',
        'salary': job.get('salary', '') or '',
        'description': job.get('description', '') or '',
        'highlights': highlights,
        'date_posted': date_posted,
    }
    # HTML-escape the JSON so it's safe inside a data attribute with single quotes
    raw_json = json.dumps(data, ensure_ascii=False)
    escaped = html_mod.escape(raw_json, quote=True).replace("'", "&#39;")
    return Markup(escaped)

# Scrape status — stored in DB settings for multi-worker support
def _get_scrape_status():
    """Read scrape status from DB (shared across workers)."""
    raw = get_setting('scrape_status', '')
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return {'running': False, 'total_new': 0, 'message': ''}


def _set_scrape_status(status):
    """Write scrape status to DB (shared across workers)."""
    set_setting('scrape_status', json.dumps(status, default=str))

# Hash the app password at startup
_hashed_password = None


def _get_hashed_password():
    global _hashed_password
    if _hashed_password is None and Config.APP_PASSWORD:
        _hashed_password = bcrypt.hashpw(
            Config.APP_PASSWORD.encode('utf-8'), bcrypt.gensalt()
        )
    return _hashed_password


# Auth decorator
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ============================================
# ROUTES
# ============================================

@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')

        if email == Config.RECIPIENT_EMAIL and Config.APP_PASSWORD and password == Config.APP_PASSWORD:
            session['logged_in'] = True
            flash('Bienvenue, Valérie!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Courriel ou mot de passe incorrect.', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    stats = get_job_stats()
    recent_jobs, _ = get_all_jobs(page=1, per_page=10, apply_conditions=True)
    return render_template('dashboard.html', stats=stats, recent_jobs=recent_jobs)


@app.route('/jobs')
@login_required
def jobs_list():
    page = request.args.get('page', 1, type=int)
    source_filter = request.args.get('source', '')
    work_type_filter = request.args.get('work_type', '')
    job_type_filter = request.args.get('job_type', '')
    applied_filter = request.args.get('applied', '')
    sort = request.args.get('sort', 'newest')
    days = request.args.get('days', 0, type=int)
    per_page = 20

    jobs, total = get_all_jobs(
        page=page, per_page=per_page,
        source=source_filter or None,
        work_type=work_type_filter or None,
        job_type=job_type_filter or None,
        applied=applied_filter or None,
        sort=sort,
        days=days or None,
    )
    total_pages = ceil(total / per_page) if total > 0 else 1

    conn = get_db()
    sources = [row['source'] for row in _fetchall(conn,
        'SELECT DISTINCT source FROM jobs ORDER BY source'
    )]
    job_types_list = [row['job_type'] for row in _fetchall(conn,
        "SELECT DISTINCT job_type FROM jobs WHERE job_type IS NOT NULL AND job_type != '' ORDER BY job_type"
    )]
    conn.close()

    return render_template(
        'jobs.html', jobs=jobs, page=page, total=total,
        total_pages=total_pages, sources=sources,
        source_filter=source_filter, work_type_filter=work_type_filter,
        job_type_filter=job_type_filter, applied_filter=applied_filter,
        sort=sort, days=days, job_types_list=job_types_list,
    )


@app.route('/favorites')
@login_required
def favorites():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    jobs, total = get_all_jobs(page=page, per_page=per_page, favorite_only=True, apply_conditions=False)
    total_pages = ceil(total / per_page) if total > 0 else 1
    return render_template(
        'favorites.html', jobs=jobs, page=page, total=total, total_pages=total_pages,
    )


@app.route('/toggle-favorite/<int:job_id>', methods=['POST'])
@login_required
def toggle_fav(job_id):
    toggle_favorite(job_id)
    return redirect(request.referrer or url_for('jobs_list'))


@app.route('/toggle-hidden/<int:job_id>', methods=['POST'])
@login_required
def toggle_hide(job_id):
    toggle_hidden(job_id)
    return redirect(request.referrer or url_for('jobs_list'))


@app.route('/toggle-applied/<int:job_id>', methods=['POST'])
@login_required
def toggle_apply(job_id):
    toggle_applied(job_id)
    return redirect(request.referrer or url_for('jobs_list'))


@app.route('/settings')
@login_required
def settings():
    conn = get_db()
    keywords = _fetchall(conn, 'SELECT * FROM search_keywords ORDER BY keyword')
    custom_boards = _fetchall(conn, 'SELECT * FROM custom_boards ORDER BY name')
    conn.close()

    work_types = json.loads(get_setting('work_types', '[]'))
    job_types = json.loads(get_setting('job_types', '[]'))
    locations = json.loads(get_setting('locations', '[]'))
    salary_min = get_setting('salary_min', '50000')
    salary_max = get_setting('salary_max', '60000')
    date_range = get_setting('date_range_days', '30')
    show_unknown = get_setting('show_unknown', '1') == '1'
    email_enabled = get_setting('email_enabled', '1') == '1'
    email_hour = get_setting('email_hour', '8')
    email_minute = get_setting('email_minute', '0')

    return render_template(
        'settings.html',
        keywords=keywords, custom_boards=custom_boards,
        work_types=work_types, job_types=job_types, locations=locations,
        salary_min=salary_min, salary_max=salary_max, date_range=date_range,
        show_unknown=show_unknown,
        email_enabled=email_enabled, email_hour=email_hour, email_minute=email_minute,
    )


@app.route('/settings/save', methods=['POST'])
@login_required
def save_settings():
    work_types = request.form.getlist('work_types')
    job_types = request.form.getlist('job_types')
    locations = [loc for loc in request.form.getlist('locations') if loc.strip()]
    salary_min = request.form.get('salary_min', '50000')
    salary_max = request.form.get('salary_max', '60000')
    date_range = request.form.get('date_range_days', '30')

    show_unknown = '1' if request.form.get('show_unknown') else '0'

    set_setting('work_types', json.dumps(work_types))
    set_setting('job_types', json.dumps(job_types))
    set_setting('locations', json.dumps(locations))
    set_setting('salary_min', salary_min)
    set_setting('salary_max', salary_max)
    set_setting('date_range_days', date_range)
    set_setting('show_unknown', show_unknown)

    flash('Conditions sauvegardées avec succès!', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/email', methods=['POST'])
@login_required
def save_email_settings():
    email_enabled = '1' if request.form.get('email_enabled') else '0'
    email_hour = request.form.get('email_hour', '8')
    email_minute = request.form.get('email_minute', '0')

    set_setting('email_enabled', email_enabled)
    set_setting('email_hour', email_hour)
    set_setting('email_minute', email_minute)

    flash('Paramètres courriel sauvegardés!', 'success')
    return redirect(url_for('settings'))


@app.route('/keywords/add', methods=['POST'])
@login_required
def add_keyword():
    keyword = request.form.get('keyword', '').strip()
    if keyword:
        conn = get_db()
        try:
            _execute(conn,
                'INSERT INTO search_keywords (keyword) VALUES (%s) ON CONFLICT (keyword) DO NOTHING', (keyword,)
            )
            flash(f'Mot-clé "{keyword}" ajouté!', 'success')
        except Exception:
            conn.rollback()
            flash('Erreur lors de l\'ajout.', 'error')
        finally:
            conn.close()
    return redirect(url_for('settings'))


@app.route('/keywords/toggle/<int:keyword_id>', methods=['POST'])
@login_required
def toggle_keyword(keyword_id):
    conn = get_db()
    _execute(conn,
        'UPDATE search_keywords SET active = NOT active WHERE id = %s', (keyword_id,)
    )
    conn.close()
    return redirect(url_for('settings'))


@app.route('/keywords/delete/<int:keyword_id>', methods=['POST'])
@login_required
def delete_keyword(keyword_id):
    conn = get_db()
    _execute(conn, 'DELETE FROM search_keywords WHERE id = %s', (keyword_id,))
    conn.close()
    flash('Mot-clé supprimé.', 'success')
    return redirect(url_for('settings'))


@app.route('/boards/add', methods=['POST'])
@login_required
def add_board():
    name = request.form.get('name', '').strip()
    base_url = request.form.get('base_url', '').strip()
    if name and base_url:
        conn = get_db()
        _execute(conn,
            'INSERT INTO custom_boards (name, base_url) VALUES (%s, %s)', (name, base_url)
        )
        conn.close()
        flash(f'Site "{name}" ajouté!', 'success')
    return redirect(url_for('settings'))


@app.route('/boards/delete/<int:board_id>', methods=['POST'])
@login_required
def delete_board(board_id):
    conn = get_db()
    _execute(conn, 'DELETE FROM custom_boards WHERE id = %s', (board_id,))
    conn.close()
    flash('Site supprimé.', 'success')
    return redirect(url_for('settings'))


def _run_scrape_with_status():
    _set_scrape_status({
        'running': True, 'total_new': 0,
        'message': 'Recherche en cours...',
        'started_at': datetime.now(timezone.utc).isoformat(),
    })
    try:
        total = run_all_scrapers(max_keywords=3)
        stats = get_job_stats()
        _set_scrape_status({
            'running': False,
            'total_new': total,
            'message': f'{total} nouvelle(s) offre(s) trouvée(s)! {stats["total"]} au total.',
        })
    except Exception as e:
        logger.error(f"Erreur scraping: {e}", exc_info=True)
        _set_scrape_status({'running': False, 'total_new': 0, 'message': f'Erreur: {e}'})


@app.route('/scrape', methods=['POST'])
@login_required
def trigger_scrape():
    status = _get_scrape_status()
    if status.get('running'):
        # Safety: check if it's been stuck for over 5 minutes
        started = status.get('started_at')
        if started:
            try:
                started_dt = datetime.fromisoformat(started)
                if (datetime.now(timezone.utc) - started_dt).total_seconds() > 300:
                    pass  # Allow restart — it's stuck
                else:
                    return jsonify({'status': 'already_running'})
            except (ValueError, TypeError):
                pass
        else:
            return jsonify({'status': 'already_running'})
    thread = threading.Thread(target=_run_scrape_with_status)
    thread.daemon = True
    thread.start()
    return jsonify({'status': 'started'})


@app.route('/scrape-status')
@login_required
def scrape_progress():
    status = _get_scrape_status()
    # Safety: if scrape has been "running" for over 5 minutes, consider it done
    if status.get('running') and status.get('started_at'):
        try:
            started_dt = datetime.fromisoformat(status['started_at'])
            elapsed = (datetime.now(timezone.utc) - started_dt).total_seconds()
            if elapsed > 300:
                status['running'] = False
                status['message'] = 'Recherche terminée!'
                _set_scrape_status(status)
        except (ValueError, TypeError):
            pass
    status.pop('started_at', None)
    return jsonify(status)


@app.route('/debug-db')
@login_required
def debug_db():
    """Debug route to see raw job data in the database."""
    conn = get_db()
    rows = _fetchall(conn,
        'SELECT id, title, company, url, location, source, work_type, salary FROM jobs ORDER BY id DESC LIMIT 15'
    )
    conn.close()
    result = []
    for r in rows:
        result.append({
            'id': r['id'],
            'title': r['title'],
            'company': r['company'],
            'url': r['url'][:80] + '...' if r['url'] and len(r['url']) > 80 else r['url'],
            'location': r['location'],
            'source': r['source'],
            'work_type': r['work_type'],
            'salary': r['salary'],
        })
    return f'<pre>{json.dumps(result, indent=2, ensure_ascii=False, default=str)}</pre>'


@app.route('/cleanup-db', methods=['POST'])
@login_required
def cleanup_db():
    """Remove bad Jobillico entries that scraped company profiles instead of jobs."""
    conn = get_db()
    _execute(conn, "DELETE FROM jobs WHERE url LIKE '%%/voir-entreprise/%%'")
    _execute(conn, "DELETE FROM jobs WHERE company = 'Ajouter aux favoris'")

    # Remove irrelevant jobs (game dev, nursing, etc.)
    from database import is_relevant, _fetchall as db_fetchall
    all_jobs = db_fetchall(conn, 'SELECT id, title, description FROM jobs')
    removed = 0
    for job in all_jobs:
        if not is_relevant({'title': job['title'], 'description': job.get('description', '')}):
            _execute(conn, 'DELETE FROM jobs WHERE id = %s', (job['id'],))
            removed += 1

    conn.close()
    flash(f'Données nettoyées! {removed} offre(s) non pertinente(s) supprimée(s).', 'success')
    return redirect(url_for('dashboard'))


@app.route('/reset-rescrape', methods=['POST'])
@login_required
def reset_and_rescrape():
    """Delete all jobs and trigger a fresh scrape with enrichment."""
    conn = get_db()
    _execute(conn, 'DELETE FROM jobs WHERE favorite = FALSE')
    conn.close()
    flash('Toutes les offres supprimées (sauf favoris). Lancement d\'une nouvelle recherche...', 'info')

    # Trigger scrape in background
    status = _get_scrape_status()
    if not status.get('running'):
        thread = threading.Thread(target=_run_scrape_with_status)
        thread.daemon = True
        thread.start()

    return jsonify({'status': 'started'})


@app.route('/send-email', methods=['POST'])
@login_required
def trigger_email():
    try:
        send_daily_digest()
        flash('Courriel envoyé avec succès!', 'success')
    except Exception as e:
        logger.error(f"Erreur envoi courriel: {e}", exc_info=True)
        flash(f'Erreur envoi courriel: {e}', 'error')
    return redirect(url_for('dashboard'))


@app.route('/test-email', methods=['POST'])
@login_required
def test_email():
    import smtplib
    from email.mime.text import MIMEText
    try:
        msg = MIMEText('Ceci est un test de Valou Job Scout! Si tu vois ce message, le courriel fonctionne.', 'plain', 'utf-8')
        msg['Subject'] = 'Valou Job Scout - Test'
        msg['From'] = Config.SENDER_EMAIL
        msg['To'] = Config.RECIPIENT_EMAIL

        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SMTP_LOGIN, Config.SMTP_PASSWORD)
            server.send_message(msg)

        flash('Courriel de test envoyé! Vérifie ta boîte de réception.', 'success')
    except Exception as e:
        logger.error(f"Test email echoue: {e}", exc_info=True)
        flash(f'Erreur: {e}', 'error')
    return redirect(url_for('dashboard'))


# ============================================
# STARTUP
# ============================================

with app.app_context():
    init_db()

init_scheduler()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
