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


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            token = get_token()

            mailbox = os.environ["MAILBOX_USER"]
            from_filter = os.environ.get("MAIL_FROM")
            subject_contains = os.environ.get("MAIL_SUBJECT_CONTAINS")

            # ONLY filter by sender (Graph is reliable here)
            params = {
                "$top": 50,
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,receivedDateTime,from",
            }

            if from_filter:
                safe_from = from_filter.replace("'", "''")
                params["$filter"] = f"from/emailAddress/address eq '{safe_from}'"

            messages = graph_get(token, f"/users/{mailbox}/messages", params=params).get("value", [])

            if not messages:
                body = {"ok": True, "message": "No messages found (after sender filter)", "sender": from_filter}
            else:
                # Apply subject filter in Python
                picked = None
                if subject_contains:
                    for m in messages:
                        if subject_contains in (m.get("subject") or ""):
                            picked = m
                            break
                else:
                    picked = messages[0]

                if not picked:
                    body = {
                        "ok": True,
                        "message": "No messages matched subject filter (scanned latest batch)",
                        "sender": from_filter,
                        "subject_contains": subject_contains,
                        "scanned": len(messages),
                        "subjects_preview": [m.get("subject") for m in messages[:10]],
                    }
                else:
                    msg_id = picked["id"]
                    atts = graph_get(token, f"/users/{mailbox}/messages/{msg_id}/attachments").get("value", [])
                    body = {
                        "ok": True,
                        "pickedMessage": picked,
                        "attachmentCount": len(atts),
                        "attachments": [
                            {"id": a.get("id"), "name": a.get("name"), "contentType": a.get("contentType"), "size": a.get("size")}
                            for a in atts
                        ],
                    }

            out = json.dumps(body, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        except Exception as e:
            err = json.dumps({"ok": False, "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err)
