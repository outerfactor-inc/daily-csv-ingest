from shared.graph_mail import find_latest_matching_csv_attachment
from .csv_parser import parse_inventory_csv


def get_latest_inventory_snapshot():
    """
    Returns a dict:
      {
        ok: bool,
        matched: bool,
        scanned: int,
        filters: {...},
        pickedMessage: {...} | None,
        attachment: {...} | None,
        csv_bytes_len: int | None,
        parsed: { rows: [...], summary: {...} } | None,
        subjects_preview: [...] | optional
      }
    """
    r = find_latest_matching_csv_attachment()

    csv_bytes = r.get("csv_bytes")
    if not csv_bytes:
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

    parsed = parse_inventory_csv(csv_bytes)

    # Keep response JSON-friendly and small-ish
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
        "csv_bytes_len": len(csv_bytes),
        "parsed": parsed,
    }
