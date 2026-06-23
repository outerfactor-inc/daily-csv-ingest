import os
from typing import Any, Dict


def get_filters() -> Dict[str, Any]:
    """
    AB inventory email targeting. Set these env vars in Vercel once AB inventory
    emails are flowing:
      INVENTORY_MAIL_SUBJECT_AB
      INVENTORY_MAIL_FROM_AB
      INVENTORY_ATTACHMENT_NAME_CONTAINS_AB   (default: ".xls" — AB sends Excel)
      INVENTORY_MAX_MESSAGES                  (shared, default: 100)
      MAILBOX_USER                            (shared)
    """
    return {
        "mailbox": os.environ["MAILBOX_USER"],
        "subject_contains": os.environ.get("INVENTORY_MAIL_SUBJECT_AB", ""),
        "from_filter": os.environ.get("INVENTORY_MAIL_FROM_AB", ""),
        "att_name_contains": os.environ.get("INVENTORY_ATTACHMENT_NAME_CONTAINS_AB", ".xls"),
        "top": int(os.environ.get("INVENTORY_MAX_MESSAGES", "100")),
    }
