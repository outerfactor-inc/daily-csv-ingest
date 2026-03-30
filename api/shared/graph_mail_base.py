import os
import requests
import base64
from typing import Any, Dict, List, Optional

GRAPH = "https://graph.microsoft.com/v1.0"


def get_ms_token() -> str:
    tenant = os.environ["MS_TENANT_ID"]
    client_id = os.environ["MS_CLIENT_ID"]
    client_secret = os.environ["MS_CLIENT_SECRET"]

    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    r = requests.post(token_url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def graph_get(token: str, path: str, params: Optional[dict] = None) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH}{path}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def graph_get_bytes(token: str, path: str, params: Optional[dict] = None) -> bytes:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH}{path}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.content


def list_recent_messages(token: str, mailbox_user: str, top: int = 100) -> list[dict]:
    params = {
        "$top": top,
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,receivedDateTime,from,sender",
    }
    return graph_get(token, f"/users/{mailbox_user}/messages", params=params).get("value", [])


def list_attachments(token: str, mailbox_user: str, msg_id: str) -> list[dict]:
    return graph_get(token, f"/users/{mailbox_user}/messages/{msg_id}/attachments").get("value", [])


def send_mail(token: str, from_email: str, to_emails: List[str], subject: str, body: str) -> None:
    """
    Send a plain-text email via Microsoft Graph sendMail API.
    """
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": e}} for e in to_emails],
        }
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{GRAPH}/users/{from_email}/sendMail"
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()


def get_attachment_bytes(token: str, mailbox_user: str, msg_id: str, att_id: str) -> bytes:
    att = graph_get(token, f"/users/{mailbox_user}/messages/{msg_id}/attachments/{att_id}")
    b64 = att.get("contentBytes")
    if b64:
        return base64.b64decode(b64)

    # Some attachment payloads omit contentBytes; fetch raw bytes via /$value.
    # This works for normal file attachments and avoids false failures.
    try:
        raw = graph_get_bytes(token, f"/users/{mailbox_user}/messages/{msg_id}/attachments/{att_id}/$value")
        if raw:
            return raw
    except Exception:
        pass

    att_type = att.get("@odata.type")
    att_name = att.get("name")
    att_content_type = att.get("contentType")
    raise ValueError(
        "Attachment has no content bytes and /$value fetch failed "
        f"(type={att_type}, name={att_name}, contentType={att_content_type})."
    )
