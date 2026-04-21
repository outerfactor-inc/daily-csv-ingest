import os
from api.shared.graph_mail_base import get_ms_token, get_attachment_bytes
from api.sell_through.ab_weekly.email_filter import find_latest_ab_weekly_sell_through_email


def get_latest_csv_snapshot() -> dict:
    token = get_ms_token()

    snap = find_latest_ab_weekly_sell_through_email(token)
    if not snap.get("matched"):
        return snap

    mailbox = snap["filters"]["MAILBOX_USER"]
    msg_id = snap["pickedMessage"]["id"]
    att_id = snap["attachment"]["id"]

    csv_bytes = get_attachment_bytes(token, mailbox, msg_id, att_id)

    snap["csv_bytes"] = csv_bytes
    snap["csv_bytes_len"] = len(csv_bytes)
    return snap
