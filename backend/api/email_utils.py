import os
import smtplib
import logging
from email.message import EmailMessage
from dotenv import load_dotenv

# Load environment variables from .env when this module is imported
load_dotenv()

def _load_credentials():
    """Return (email_user, email_pass) from environment, logging their presence (masked)."""
    email_user = os.getenv('EMAIL_USER')
    email_pass = os.getenv('EMAIL_PASS')
    # Strip any whitespace that may be present in the app password (e.g., groups separated by spaces)
    if email_pass:
        email_pass = email_pass.replace(' ', '')
    if email_user:
        masked = email_user[:2] + '***' + email_user[-2:]
        logging.info(f'Email credentials loaded for user: {masked}')
    else:
        logging.warning('EMAIL_USER not set in environment')
    if not email_user or not email_pass:
        logging.error('EMAIL_USER or EMAIL_PASS missing – email will not be sent')
    return email_user, email_pass

def send_email(subject: str, body: str, recipient: str) -> bool:
    """Send an email via Gmail SMTP using STARTTLS. Returns True on success, False otherwise."""
    email_user, email_pass = _load_credentials()
    if not email_user or not email_pass:
        return False

    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = email_user
    message['To'] = recipient
    message.set_content(body)

    try:
        # First attempt SSL connection (port 465)
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(email_user, email_pass)
            smtp.send_message(message)
        logging.info(f'Email sent successfully via SSL to {recipient}')
        return True
    except Exception as ssl_exc:
        logging.warning(f'SMTP_SSL failed: {ssl_exc}. Trying STARTTLS...')
        try:
            with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(email_user, email_pass)
                smtp.send_message(message)
            logging.info(f'Email sent successfully via STARTTLS to {recipient}')
            return True
        except Exception as starttls_exc:
            logging.error(f'Failed to send email via both SSL and STARTTLS: {starttls_exc}')
            return False

def send_verification_code(recipient: str, code: str) -> None:
    """Send a 6‑digit verification code to a new or password‑reset request."""
    subject = 'HR Management System Verification Code'
    body = f'Your verification code is: {code}'
    if not send_email(subject, body, recipient):
        print('Verification email failed for', recipient)

def send_password_reset_code(recipient: str, code: str) -> None:
    """Send a password‑reset code to the user."""
    subject = 'HR Management System Password Reset Code'
    body = f'Your password reset code is: {code}'
    if not send_email(subject, body, recipient):
        print('Password reset email failed for', recipient)
