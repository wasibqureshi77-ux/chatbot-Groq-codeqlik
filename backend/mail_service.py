import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

MAIL_SERVICE_URL = os.getenv("MAIL_SERVICE_URL", "http://127.0.0.1:9000")
MAIL_SERVICE_SECRET = os.getenv("MAIL_SERVICE_SECRET", "change_this_internal_secret")


def _post_json(endpoint: str, payload: dict) -> dict:
    url = MAIL_SERVICE_URL.rstrip("/") + endpoint
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Mail-Service-Secret": MAIL_SERVICE_SECRET,
    }
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        response_data = response.read().decode("utf-8")
        try:
            return json.loads(response_data)
        except json.JSONDecodeError:
            return {"raw": response_data}


def send_email(to: str, subject: str, html: str, text: str = "", from_email: str = None, from_name: str = None) -> dict:
    payload = {
        "to": to,
        "subject": subject,
        "html": html,
        "text": text or html,
    }
    if from_email:
        payload["fromEmail"] = from_email
    if from_name:
        payload["fromName"] = from_name
    return _post_json("/send-email", payload)
