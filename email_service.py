import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import Config
from database import get_unemailed_jobs, mark_jobs_emailed

logger = logging.getLogger(__name__)

EMAIL_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
    background-color: #FAF7F2;
    color: #3D3228;
    margin: 0;
    padding: 0;
  }}
  .container {{
    max-width: 600px;
    margin: 0 auto;
    padding: 30px 20px;
  }}
  .header {{
    text-align: center;
    padding: 20px 0;
    border-bottom: 2px solid #E8DFD4;
  }}
  .header h1 {{
    font-family: Georgia, 'Times New Roman', serif;
    color: #6B5B4E;
    font-size: 28px;
    font-weight: 400;
    margin: 0;
  }}
  .header p {{
    color: #9B8E82;
    font-size: 14px;
    margin-top: 8px;
  }}
  .job-card {{
    background: #FFFFFF;
    border: 1px solid #E8DFD4;
    border-radius: 12px;
    padding: 20px;
    margin: 16px 0;
  }}
  .job-card h3 {{
    font-family: Georgia, 'Times New Roman', serif;
    color: #3D3228;
    margin: 0 0 8px 0;
    font-size: 18px;
  }}
  .job-card h3 a {{
    color: #6B5B4E;
    text-decoration: none;
  }}
  .job-card h3 a:hover {{
    text-decoration: underline;
  }}
  .job-meta {{
    color: #9B8E82;
    font-size: 13px;
    margin-bottom: 10px;
  }}
  .job-meta span {{
    margin-right: 12px;
  }}
  .badge {{
    display: inline-block;
    background: #EDE8E0;
    color: #6B5B4E;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    margin-right: 6px;
  }}
  .description {{
    color: #5A4E43;
    font-size: 14px;
    line-height: 1.5;
    margin-top: 10px;
  }}
  .footer {{
    text-align: center;
    padding: 20px 0;
    color: #B5A99A;
    font-size: 12px;
    border-top: 1px solid #E8DFD4;
    margin-top: 20px;
  }}
  .btn {{
    display: inline-block;
    background: #6B5B4E;
    color: #FFFFFF;
    padding: 8px 20px;
    border-radius: 20px;
    text-decoration: none;
    font-size: 13px;
    margin-top: 10px;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Valou Job Scout</h1>
    <p>{count} nouvelle(s) offre(s) aujourd'hui</p>
  </div>
  {job_cards}
  <div class="footer">
    <p>Valou Job Scout &mdash; Ta chercheuse d'emploi personnelle</p>
  </div>
</div>
</body>
</html>
'''

JOB_CARD_TEMPLATE = '''
<div class="job-card">
  <h3><a href="{url}">{title}</a></h3>
  <div class="job-meta">
    <span>{company}</span>
    <span>{location}</span>
  </div>
  {badges}
  {salary_html}
  <div class="description">{description}</div>
  <a href="{url}" class="btn">Voir l'offre</a>
</div>
'''


def send_daily_digest():
    jobs = get_unemailed_jobs()
    if not jobs:
        logger.info("Aucune nouvelle offre a envoyer.")
        return

    job_cards_html = []
    job_ids = []

    for job in jobs:
        badges = ''
        if job['work_type']:
            labels = {
                'teletravail': 'Teletravail',
                'hybride': 'Hybride',
                'presentiel': 'Presentiel',
            }
            badge_label = labels.get(job['work_type'], job['work_type'])
            badges = f'<span class="badge">{badge_label}</span>'
        if job['source']:
            badges += f'<span class="badge">{job["source"]}</span>'

        salary_html = ''
        if job['salary']:
            salary_html = f'<div class="job-meta"><span>Salaire: {job["salary"]}</span></div>'

        card = JOB_CARD_TEMPLATE.format(
            url=job['url'],
            title=job['title'],
            company=job['company'] or 'Entreprise non specifiee',
            location=job['location'] or '',
            badges=badges,
            salary_html=salary_html,
            description=job['description'][:200] if job['description'] else '',
        )
        job_cards_html.append(card)
        job_ids.append(job['id'])

    html_content = EMAIL_TEMPLATE.format(
        count=len(jobs),
        job_cards='\n'.join(job_cards_html),
    )

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Valou Job Scout - {len(jobs)} nouvelle(s) offre(s)'
        msg['From'] = Config.SENDER_EMAIL
        msg['To'] = Config.RECIPIENT_EMAIL

        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SMTP_LOGIN, Config.SMTP_PASSWORD)
            server.send_message(msg)

        mark_jobs_emailed(job_ids)
        logger.info(f"Courriel envoye avec {len(jobs)} offre(s).")

    except Exception as e:
        logger.error(f"Erreur envoi courriel: {e}")
