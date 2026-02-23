import os
from typing import Any, Dict

from api.shared.graph_mail_base import list_attachments, list_recent_messages


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _get_addr(msg: dict, field: str) -> str:
    try:
        return _norm(msg.get(field, {}).get("emailAddress", {}).get("address"))
    except Exception:
        return ""


def find_latest_ab_sell_through_email(token: str) -> Dict[str, Any]:
    mailbox = os.environ.get("TARIN_MAILBOX") or os.environ["TARIN_MAILBOX"]
    subject_contains = _norm(os.environ.get("SELL_THROUGH_MAIL_SUBJECT_AB"))
    from_filter = _norm(os.environ.get("SELL_THROUGH_MAIL_FROM_AB"))
    att_name_contains = _norm(os.environ.get("ATTACHMENT_NAME_CONTAINS_AB", ".csv"))
    top = int(os.environ.get("SELL_THROUGH_AB_MAX_MESSAGES", "100"))

    messages = list_recent_messages(token, mailbox, top=top)

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

        atts = list_attachments(token, mailbox, msg["id"])
        matching = [a for a in atts if att_name_contains in _norm(a.get("name"))]
        if not matching:
            continue

        att0 = matching[0]
        return {
            "matched": True,
            "scanned": scanned,
            "filters": {
                "MAILBOX_USER": mailbox,
                "MAIL_SUBJECT_CONTAINS": subject_contains or None,
                "MAIL_FROM": from_filter or None,
                "ATTACHMENT_NAME_CONTAINS": att_name_contains or None,
            },
            "pickedMessage": {
                "id": msg.get("id"),
                "subject": msg.get("subject"),
                "receivedDateTime": msg.get("receivedDateTime"),
                "from": msg.get("from"),
                "sender": msg.get("sender"),
            },
            "attachment": {
                "id": att0.get("id"),
                "name": att0.get("name"),
                "contentType": att0.get("contentType"),
                "size": att0.get("size"),
            },
        }

    return {
        "matched": False,
        "scanned": len(messages),
        "filters": {
            "MAILBOX_USER": mailbox,
            "MAIL_SUBJECT_CONTAINS": subject_contains or None,
            "MAIL_FROM": from_filter or None,
            "ATTACHMENT_NAME_CONTAINS": att_name_contains or None,
        },
        "subjects_preview": [m.get("subject") for m in messages[:15]],
    }