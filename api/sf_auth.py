import os
import time
import requests
import jwt

def get_salesforce_token():
    login_url = os.environ["SF_LOGIN_URL"].rstrip("/")  # e.g. https://login.salesforce.com

    payload = {
        "iss": os.environ["SF_CLIENT_ID"],      # Connected App -> Consumer Key
        "sub": os.environ["SF_USERNAME"],       # SF user username
        "aud": login_url,                       # must match the host you’re using
        "exp": int(time.time()) + 300,          # 5 min
    }

    private_key = os.environ["SF_PRIVATE_KEY"].replace("\\n", "\n").strip()

    assertion = jwt.encode(payload, private_key, algorithm="RS256")
    if isinstance(assertion, bytes):
        assertion = assertion.decode("utf-8")

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
