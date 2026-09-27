import logging

from flask_mail import Message

from extensions import mail

logger = logging.getLogger(__name__)


def send_email(subject, recipients, body, html=None):
    """Send an email via the Flask-Mail SMTP config. Must be called inside an app context."""
    if not recipients:
        return False, 'No recipient address provided'
    try:
        msg = Message(subject=subject, recipients=recipients, body=body, html=html)
        mail.send(msg)
        return True, None
    except Exception as e:
        logger.exception('Failed to send email to %s', recipients)
        return False, str(e)
