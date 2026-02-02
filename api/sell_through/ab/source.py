import os
from api.shared.graph_mail import find_latest_message_with_attachment

def get_latest_csv_snapshot() -> dict:
    return find_latest_message_with_attachment(
        mailbox_user=os.environ["MAILBOX_USER"],
        subject_contains=os.environ.get("SELL_THROUGH_MAIL_SUBJECT_AB"),
        from_email=os.environ.get("SELL_THROUGH_MAIL_FROM_AB"),
        attachment_name_contains=os.environ.get("SELL_THROUGH_ATTACHMENT_NAME_CONTAINS", ".csv"),
        max_messages=int(os.environ.get("SELL_THROUGH_MAX_MESSAGES", "100")),
    )
