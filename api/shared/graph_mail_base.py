import os
import requests
import base64
from typing import Any, Dict, Optional

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


def list_recent_messages(token: str, mailbox_user: str, top: int = 100) -> list[dict]:
    params = {
        "$top": top,
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,receivedDateTime,from,sender",
    }
    return graph_get(token, f"/users/{mailbox_user}/messages", params=params).get("value", [])


def list_attachments(token: str, mailbox_user: str, msg_id: str) -> list[dict]:
    return graph_get(token, f"/users/{mailbox_user}/messages/{msg_id}/attachments").get("value", [])


def get_attachment_bytes(token: str, mailbox_user: str, msg_id: str, att_id: str) -> bytes:
    att = graph_get(token, f"/users/{mailbox_user}/messages/{msg_id}/attachments/{att_id}")
    b64 = att.get("contentBytes")
    if not b64:
        raise ValueError("Attachment has no contentBytes (not a file attachment?)")
    return base64.b64decode(b64)
