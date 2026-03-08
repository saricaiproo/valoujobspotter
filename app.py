import json
import logging
import threading
from functools import wraps
from math import ceil

import bcrypt
from flask import Flask, render_template, request, redirect, url_for, session, flash

from config import Config
from database import (
    init_db, get_db, get_job_stats, get_all_jobs, get_setting, set_setting,
    get_active_keywords, toggle_favorite, toggle_hidden,
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
            flash('Bienvenue, Valerie!', 'success')
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
    conn = get_db()
    recent_jobs = conn.execute(
        'SELECT * FROM jobs WHERE hidden = 0 ORDER BY date_scraped DESC LIMIT 10'
    ).fetchall()
    conn.close()
    return render_template('dashboard.html', stats=stats, recent_jobs=recent_jobs)


@app.route('/jobs')
@login_required
def jobs_list():
    page = request.args.get('page', 1, type=int)
    source_filter = request.args.get('source', '')
    per_page = 20

    jobs, total = get_all_jobs(
        page=page, per_page=per_page, source=source_filter or None
    )
    total_pages = ceil(total / per_page) if total > 0 else 1

    conn = get_db()
    sources = [row['source'] for row in conn.execute(
        'SELECT DISTINCT source FROM jobs ORDER BY source'
    ).fetchall()]
    conn.close()

    return render_template(
        'jobs.html', jobs=jobs, page=page, total=total,
        total_pages=total_pages, sources=sources, source_filter=source_filter,
    )


@app.route('/favorites')
@login_required
def favorites():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    jobs, total = get_all_jobs(page=page, per_page=per_page, favorite_only=True)
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


@app.route('/settings')
@login_required
def settings():
    conn = get_db()
    keywords = conn.execute('SELECT * FROM search_keywords ORDER BY keyword').fetchall()
    custom_boards = conn.execute('SELECT * FROM custom_boards ORDER BY name').fetchall()
    conn.close()

    work_types = json.loads(get_setting('work_types', '[]'))
    job_types = json.loads(get_setting('job_types', '[]'))
    locations = json.loads(get_setting('locations', '[]'))
    salary_min = get_setting('salary_min', '50000')
    salary_max = get_setting('salary_max', '60000')
    date_range = get_setting('date_range_days', '30')
    email_enabled = get_setting('email_enabled', '1') == '1'
    email_hour = get_setting('email_hour', '8')
    email_minute = get_setting('email_minute', '0')

    return render_template(
        'settings.html',
        keywords=keywords, custom_boards=custom_boards,
        work_types=work_types, job_types=job_types, locations=locations,
        salary_min=salary_min, salary_max=salary_max, date_range=date_range,
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

    set_setting('work_types', json.dumps(work_types))
    set_setting('job_types', json.dumps(job_types))
    set_setting('locations', json.dumps(locations))
    set_setting('salary_min', salary_min)
    set_setting('salary_max', salary_max)
    set_setting('date_range_days', date_range)

    flash('Filtres sauvegardes avec succes!', 'success')
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

    flash('Parametres courriel sauvegardes!', 'success')
    return redirect(url_for('settings'))


@app.route('/keywords/add', methods=['POST'])
@login_required
def add_keyword():
    keyword = request.form.get('keyword', '').strip()
    if keyword:
        conn = get_db()
        try:
            conn.execute(
                'INSERT OR IGNORE INTO search_keywords (keyword) VALUES (?)', (keyword,)
            )
            conn.commit()
            flash(f'Mot-cle "{keyword}" ajoute!', 'success')
        except Exception:
            flash('Erreur lors de l\'ajout.', 'error')
        finally:
            conn.close()
    return redirect(url_for('settings'))


@app.route('/keywords/toggle/<int:keyword_id>', methods=['POST'])
@login_required
def toggle_keyword(keyword_id):
    conn = get_db()
    conn.execute(
        'UPDATE search_keywords SET active = NOT active WHERE id = ?', (keyword_id,)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('settings'))


@app.route('/keywords/delete/<int:keyword_id>', methods=['POST'])
@login_required
def delete_keyword(keyword_id):
    conn = get_db()
    conn.execute('DELETE FROM search_keywords WHERE id = ?', (keyword_id,))
    conn.commit()
    conn.close()
    flash('Mot-cle supprime.', 'success')
    return redirect(url_for('settings'))


@app.route('/boards/add', methods=['POST'])
@login_required
def add_board():
    name = request.form.get('name', '').strip()
    base_url = request.form.get('base_url', '').strip()
    if name and base_url:
        conn = get_db()
        conn.execute(
            'INSERT INTO custom_boards (name, base_url) VALUES (?, ?)', (name, base_url)
        )
        conn.commit()
        conn.close()
        flash(f'Site "{name}" ajoute!', 'success')
    return redirect(url_for('settings'))


@app.route('/boards/delete/<int:board_id>', methods=['POST'])
@login_required
def delete_board(board_id):
    conn = get_db()
    conn.execute('DELETE FROM custom_boards WHERE id = ?', (board_id,))
    conn.commit()
    conn.close()
    flash('Site supprime.', 'success')
    return redirect(url_for('settings'))


@app.route('/scrape', methods=['POST'])
@login_required
def trigger_scrape():
    flash('Recherche lancee en arriere-plan! Rafraichis la page dans 2-3 minutes.', 'info')
    thread = threading.Thread(target=run_all_scrapers, kwargs={'max_keywords': 5})
    thread.daemon = True
    thread.start()
    return redirect(url_for('dashboard'))


@app.route('/debug-scrape')
@login_required
def debug_scrape():
    """Temporary debug route to see actual HTML structure of job sites."""
    import requests
    from bs4 import BeautifulSoup
    results = {}

    sites = {
        'Jobillico': 'https://www.jobillico.com/recherche-emploi?skwd=social+media+manager&sloc=Montreal',
        'Jobboom': 'https://www.jobboom.com/fr/recherche?keywords=social+media+manager&location=Montreal',
        'Indeed RSS': 'https://ca.indeed.com/rss?q=social+media+manager&l=Montreal',
        'LinkedIn': 'https://www.linkedin.com/jobs/search/?keywords=social+media+manager&location=Montreal',
    }

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'fr-CA,fr;q=0.9,en;q=0.7',
    }

    for name, url in sites.items():
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(resp.text, 'lxml')

            # Log all tags with class attributes to find job card patterns
            all_classes = set()
            for tag in soup.find_all(True, class_=True):
                for cls in tag.get('class', []):
                    if any(kw in cls.lower() for kw in ['job', 'offer', 'result', 'card', 'listing', 'item', 'emploi', 'offre', 'poste']):
                        all_classes.add(f"{tag.name}.{cls}")

            # Get first 500 chars of interesting elements
            sample = ', '.join(sorted(all_classes)[:30])
            results[name] = {
                'status': resp.status_code,
                'size': len(resp.text),
                'job_classes': sample or 'Aucune classe trouvee',
            }
            logger.info(f"[DEBUG] {name} ({resp.status_code}): Classes trouvees: {sample}")
        except Exception as e:
            results[name] = {'status': 'error', 'error': str(e)}
            logger.error(f"[DEBUG] {name}: {e}")

    return f'<pre>{json.dumps(results, indent=2, ensure_ascii=False)}</pre>'


@app.route('/send-email', methods=['POST'])
@login_required
def trigger_email():
    try:
        send_daily_digest()
        flash('Courriel envoye avec succes!', 'success')
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

        flash('Courriel de test envoye! Verifie ta boite de reception.', 'success')
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
