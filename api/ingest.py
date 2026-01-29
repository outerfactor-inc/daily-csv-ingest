import os
import json
import requests
from http.server import BaseHTTPRequestHandler

GRAPH = "https://graph.microsoft.com/v1.0"


def get_token():
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


def graph_get(token, path, params=None):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH}{path}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _get_addr(obj: dict, field: str) -> str:
    """
    Extracts email address from Graph message fields like:
    msg["from"]["emailAddress"]["address"]
    msg["sender"]["emailAddress"]["address"]
    """
    try:
        return _norm(obj.get(field, {}).get("emailAddress", {}).get("address"))
    except Exception:
        return ""


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            token = get_token()

            mailbox = os.environ["MAILBOX_USER"]  # required
            subject_contains = _norm(os.environ.get("MAIL_SUBJECT_CONTAINS"))
            from_filter = _norm(os.environ.get("MAIL_FROM"))
            att_name_contains = _norm(os.environ.get("ATTACHMENT_NAME_CONTAINS"))

            # Fetch recent messages. No $filter to avoid Graph "InefficientFilter".
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
                sender_addr = _get_addr(msg, "sender")  # sometimes differs

                # 1) subject filter (optional)
                if subject_contains and subject_contains not in subj:
                    continue

                # 2) from filter (optional) - match either from or sender
                if from_filter and (from_filter != from_addr and from_filter != sender_addr):
                    continue

                # 3) attachments filter (optional)
                msg_id = msg["id"]
                atts = graph_get(token, f"/users/{mailbox}/messages/{msg_id}/attachments").get("value", [])

                # If user asked for attachment name filter, require at least one match
                if att_name_contains:
                    matching_atts = [
                        a for a in atts
                        if att_name_contains in _norm(a.get("name"))
                    ]
                    if not matching_atts:
                        continue
                    chosen_atts = matching_atts
                else:
                    chosen_atts = atts

                # Found a message that matches all enabled filters
                body = {
                    "ok": True,
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
                    "attachmentCount": len(atts),
                    "matchedAttachments": [
                        {
                            "id": a.get("id"),
                            "name": a.get("name"),
                            "contentType": a.get("contentType"),
                            "size": a.get("size"),
                        }
                        for a in chosen_atts
                    ],
                }

                out = json.dumps(body, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)
                return

            # If we got here, nothing matched
            body = {
                "ok": True,
                "matched": False,
                "message": "No messages matched filters in the scanned window",
                "scanned": len(messages),
                "filters": {
                    "MAILBOX_USER": mailbox,
                    "MAIL_SUBJECT_CONTAINS": subject_contains or None,
                    "MAIL_FROM": from_filter or None,
                    "ATTACHMENT_NAME_CONTAINS": att_name_contains or None,
                },
                "subjects_preview": [m.get("subject") for m in messages[:15]],
            }
            out = json.dumps(body, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        except requests.HTTPError as e:
            details = None
            try:
                details = e.response.json()
            except Exception:
                details = e.response.text if e.response is not None else None

            err = json.dumps({"ok": False, "error": str(e), "details": details}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err)

        except Exception as e:
            err = json.dumps({"ok": False, "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err)


# testing csv parser
from .csv_parser import parse_inventory_csv

result = parse_inventory_csv(csv_bytes)
