import os
from typing import Any, Dict


def get_filters() -> Dict[str, Any]:
    """
    3Eye inventory email targeting. Namespaced env vars so each distributor can
    point at a different email:
      INVENTORY_MAIL_SUBJECT_3E
      INVENTORY_MAIL_FROM_3E
      INVENTORY_ATTACHMENT_NAME_CONTAINS_3E   (default: ".csv")
      INVENTORY_MAX_MESSAGES                  (shared, default: 100)
      MAILBOX_USER                            (shared)
    """
    return {
        "mailbox": os.environ["MAILBOX_USER"],
        "subject_contains": os.environ.get("INVENTORY_MAIL_SUBJECT_3E", ""),
        "from_filter": os.environ.get("INVENTORY_MAIL_FROM_3E", ""),
        "att_name_contains": os.environ.get("INVENTORY_ATTACHMENT_NAME_CONTAINS_3E", ".csv"),
        "top": int(os.environ.get("INVENTORY_MAX_MESSAGES", "100")),
    }
