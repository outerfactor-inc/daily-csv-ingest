import os
import json
import time
import requests
import jwt
from http.server import BaseHTTPRequestHandler


def _read_private_key() -> str:
    """
    Vercel env vars often store multi-line keys either:
    - as real newlines, or
    - with literal '\n' sequences.
    This normalizes it.
    """
    key = os.environ["SF_PRIVATE_KEY"]
    return key.replace("\\n", "\n")


def get_salesforce_token():
    login_url = os.environ.get("SF_LOGIN_URL", "https://login.salesforce.com").rstrip("/")
    payload = {
        "iss": os.environ["SF_CLIENT_ID"],     # Connected App Consumer Key
        "sub": os.environ["SF_USERNAME"],      # SF integration user username
        "aud": login_url,
        "exp": int(time.time()) + 300,
    }

    assertion = jwt.encode(payload, _read_private_key(), algorithm="RS256")

    r = requests.post(
        f"{login_url}/services/oauth2/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            tok = get_salesforce_token()
            body = {
                "ok": True,
                "instance_url": tok.get("instance_url"),
                "token_type": tok.get("token_type"),
                "scope": tok.get("scope"),
                # do NOT return access_token
            }
            out = json.dumps(body, indent=2).encode("utf-8")
            self.send_response(200)
        except requests.HTTPError as e:
            details = None
            try:
                details = e.response.json()
            except Exception:
                details = e.response.text

            out = json.dumps(
                {"ok": False, "error": str(e), "details": details},
                indent=2,
            ).encode("utf-8")
            self.send_response(500)
        except Exception as e:
            out = json.dumps({"ok": False, "error": str(e)}, indent=2).encode("utf-8")
            self.send_response(500)

        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)
