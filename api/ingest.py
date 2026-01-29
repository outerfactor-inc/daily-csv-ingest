import os
import json
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode

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

            # Build an OData filter. We’ll keep it simple/robust.
            filters = []
            if from_filter:
                # from/emailAddress/address eq '...'
                filters.append(f"from/emailAddress/address eq '{from_filter}'")
            if subject_contains:
                # contains(subject,'...')
                filters.append(f"contains(subject,'{subject_contains}')")

            filter_str = " and ".join(filters) if filters else None

            params = {
                "$top": 5,
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,receivedDateTime,from",
            }
            if filter_str:
                params["$filter"] = filter_str

            # Get recent messages from mailbox
            messages = graph_get(token, f"/users/{mailbox}/messages", params=params).get("value", [])
            if not messages:
                body = {"ok": True, "message": "No matching messages found", "filter": filter_str}
            else:
                msg = messages[0]
                msg_id = msg["id"]

                # List attachments metadata
                atts = graph_get(token, f"/users/{mailbox}/messages/{msg_id}/attachments").get("value", [])
                body = {
                    "ok": True,
                    "pickedMessage": msg,
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
