import os
import base64
import requests

GRAPH = "https://graph.microsoft.com/v1.0"


def get_token() -> str:
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


def graph_get(token: str, path: str, params=None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH}{path}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def graph_get_attachment_bytes(token: str, mailbox: str, msg_id: str, att_id: str) -> bytes:
    att = graph_get(token, f"/users/{mailbox}/messages/{msg_id}/attachments/{att_id}")
    b64 = att.get("contentBytes")
    if not b64:
        raise ValueError("Attachment has no contentBytes (not a file attachment?)")
    return base64.b64decode(b64)


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _get_addr(msg: dict, field: str) -> str:
    try:
        return _norm(msg.get(field, {}).get("emailAddress", {}).get("address"))
    except Exception:
        return ""


def find_latest_matching_csv_attachment():
    """
    Uses env vars:
      MAILBOX_USER (required)
      MAIL_SUBJECT_CONTAINS (optional)
      MAIL_FROM (optional)
      ATTACHMENT_NAME_CONTAINS (optional)

    Returns:
      dict with keys:
        mailbox, pickedMessage, attachment, csv_bytes, scanned
    """
    token = get_token()

    mailbox = os.environ["MAILBOX_USER"]
    subject_contains = _norm(os.environ.get("MAIL_SUBJECT_CONTAINS"))
    from_filter = _norm(os.environ.get("MAIL_FROM"))
    att_name_contains = _norm(os.environ.get("ATTACHMENT_NAME_CONTAINS"))

    params = {
        "$top": 100,
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,receivedDateTime,from,sender",
    }

    messages = graph_get(token, f"/users/{mailbox}/messages", params=params).get("value", [])

    scanned = 0
    for msg in messages:
        scanned += 1

        subj = _norm(msg.get("subject"))
        from_addr = _get_addr(msg, "from")
        sender_addr = _get_addr(msg, "sender")

        if subject_contains and subject_contains not in subj:
            continue

        if from_filter and (from_filter != from_addr and from_filter != sender_addr):
            continue

        msg_id = msg["id"]
        atts = graph_get(token, f"/users/{mailbox}/messages/{msg_id}/attachments").get("value", [])

        if att_name_contains:
            chosen = [a for a in atts if att_name_contains in _norm(a.get("name"))]
            if not chosen:
                continue
        else:
            chosen = atts

        if not chosen:
            continue

        att0 = chosen[0]
        csv_bytes = graph_get_attachment_bytes(token, mailbox, msg_id, att0["id"])

        return {
            "mailbox": mailbox,
            "pickedMessage": msg,
            "attachment": att0,
            "allAttachmentsMatched": chosen,
            "attachmentCount": len(atts),
            "csv_bytes": csv_bytes,
            "scanned": scanned,
            "filters": {
                "MAILBOX_USER": mailbox,
                "MAIL_SUBJECT_CONTAINS": subject_contains or None,
                "MAIL_FROM": from_filter or None,
                "ATTACHMENT_NAME_CONTAINS": att_name_contains or None,
            },
        }

    return {
        "mailbox": mailbox,
        "pickedMessage": None,
        "attachment": None,
        "csv_bytes": None,
        "scanned": len(messages),
        "filters": {
            "MAILBOX_USER": mailbox,
            "MAIL_SUBJECT_CONTAINS": subject_contains or None,
            "MAIL_FROM": from_filter or None,
            "ATTACHMENT_NAME_CONTAINS": att_name_contains or None,
        },
        "subjects_preview": [m.get("subject") for m in messages[:15]],
    }
