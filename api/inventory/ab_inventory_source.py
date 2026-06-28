import os

# Reuse the existing Graph helpers (read-only import; graph_mail.py is unchanged).
from api.shared.graph_mail import (
    get_token,
    graph_get,
    graph_get_attachment_bytes,
    _norm,
    _get_addr,
)
from api.inventory.ab_xls_parser import parse_ab_inventory_xls


def _find_latest_ab_inventory_attachment() -> dict:
    """
    AB-specific email scan. Uses AB-namespaced env vars so it never disturbs the
    3Eye inventory filters (MAIL_SUBJECT_CONTAINS / MAIL_FROM / ...):
      MAILBOX_USER (required, shared)
      INVENTORY_MAIL_SUBJECT_AB (optional, substring match)
      INVENTORY_MAIL_FROM_AB (optional)
      INVENTORY_ATTACHMENT_NAME_CONTAINS_AB (optional, default ".xls")
      INVENTORY_MAX_MESSAGES (optional, default "100")
    """
    token = get_token()

    mailbox = os.environ["MAILBOX_USER"]
    subject_contains = _norm(os.environ.get("INVENTORY_MAIL_SUBJECT_AB"))
    from_filter = _norm(os.environ.get("INVENTORY_MAIL_FROM_AB"))
    att_name_contains = _norm(os.environ.get("INVENTORY_ATTACHMENT_NAME_CONTAINS_AB", ".xls"))
    top = int(os.environ.get("INVENTORY_MAX_MESSAGES", "100"))

    params = {
        "$top": top,
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,receivedDateTime,from,sender",
    }

    messages = graph_get(token, f"/users/{mailbox}/messages", params=params).get("value", [])

    filters_echo = {
        "MAILBOX_USER": mailbox,
        "MAIL_SUBJECT_CONTAINS": subject_contains or None,
        "MAIL_FROM": from_filter or None,
        "ATTACHMENT_NAME_CONTAINS": att_name_contains or None,
    }

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
        else:
            chosen = atts

        if not chosen:
            continue

        att0 = chosen[0]
        file_bytes = graph_get_attachment_bytes(token, mailbox, msg_id, att0["id"])

        return {
            "mailbox": mailbox,
            "pickedMessage": msg,
            "attachment": att0,
            "file_bytes": file_bytes,
            "scanned": scanned,
            "filters": filters_echo,
        }

    return {
        "mailbox": mailbox,
        "pickedMessage": None,
        "attachment": None,
        "file_bytes": None,
        "scanned": len(messages),
        "filters": filters_echo,
        "subjects_preview": [m.get("subject") for m in messages[:15]],
    }


def get_latest_ab_inventory_snapshot() -> dict:
    """
    Same return shape as api.inventory.inventory_source.get_latest_inventory_snapshot,
    so the AB ingest handler mirrors the 3Eye one.
    """
    r = _find_latest_ab_inventory_attachment()

    file_bytes = r.get("file_bytes")
    if not file_bytes:
        return {
            "ok": True,
            "matched": False,
            "scanned": r.get("scanned"),
            "filters": r.get("filters"),
            "subjects_preview": r.get("subjects_preview", []),
            "pickedMessage": None,
            "attachment": None,
            "csv_bytes_len": None,
            "parsed": None,
        }

    parsed = parse_ab_inventory_xls(file_bytes)

    attachment = r.get("attachment") or {}
    msg = r.get("pickedMessage") or {}

    return {
        "ok": True,
        "matched": True,
        "scanned": r.get("scanned"),
        "filters": r.get("filters"),
        "pickedMessage": {
            "id": msg.get("id"),
            "subject": msg.get("subject"),
            "receivedDateTime": msg.get("receivedDateTime"),
            "from": msg.get("from"),
            "sender": msg.get("sender"),
        },
        "attachment": {
            "id": attachment.get("id"),
            "name": attachment.get("name"),
            "contentType": attachment.get("contentType"),
            "size": attachment.get("size"),
        },
        "csv_bytes_len": len(file_bytes),
        "parsed": parsed,
    }
