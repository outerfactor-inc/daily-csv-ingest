from typing import Any, Callable, Dict
from api.shared.graph_mail_base import (
    get_ms_token,
    list_recent_messages,
    list_attachments,
    get_attachment_bytes,
)


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _get_addr(msg: dict, field: str) -> str:
    try:
        return _norm(msg.get(field, {}).get("emailAddress", {}).get("address"))
    except Exception:
        return ""


def find_latest_inventory_email(token: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generic "find the latest matching inventory email" scan, shared by all
    distributors. `filters` is produced by a distributor's email_filter module:
      {
        "mailbox": str,
        "subject_contains": str | "",
        "from_filter": str | "",
        "att_name_contains": str,
        "top": int,
      }
    """
    mailbox = filters["mailbox"]
    subject_contains = _norm(filters.get("subject_contains"))
    from_filter = _norm(filters.get("from_filter"))
    att_name_contains = _norm(filters.get("att_name_contains") or ".csv")
    top = int(filters.get("top") or 100)

    filters_echo = {
        "MAILBOX_USER": mailbox,
        "MAIL_SUBJECT_CONTAINS": subject_contains or None,
        "MAIL_FROM": from_filter or None,
        "ATTACHMENT_NAME_CONTAINS": att_name_contains or None,
    }

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
            "filters": filters_echo,
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
        "filters": filters_echo,
        "pickedMessage": None,
        "attachment": None,
        "subjects_preview": [m.get("subject") for m in messages[:15]],
    }


def get_latest_inventory_snapshot(
    filters: Dict[str, Any],
    parser_fn: Callable[[bytes], Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Fetch the latest matching inventory email for one distributor, download the
    CSV, and parse it with that distributor's parser. Returns a snapshot dict
    consumed by the shared ingest handler.
    """
    token = get_ms_token()
    snap = find_latest_inventory_email(token, filters)

    if not snap.get("matched"):
        snap["ok"] = True
        snap["csv_bytes"] = None
        snap["csv_bytes_len"] = None
        snap["parsed"] = None
        return snap

    mailbox = snap["filters"]["MAILBOX_USER"]
    msg_id = snap["pickedMessage"]["id"]
    att_id = snap["attachment"]["id"]

    csv_bytes = get_attachment_bytes(token, mailbox, msg_id, att_id)
    parsed = parser_fn(csv_bytes)

    snap["ok"] = True
    snap["csv_bytes"] = csv_bytes
    snap["csv_bytes_len"] = len(csv_bytes)
    snap["parsed"] = parsed
    return snap
