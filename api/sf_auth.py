import jwt
import time

def get_salesforce_token():
    payload = {
        "iss": os.environ["SF_CLIENT_ID"],
        "sub": os.environ["SF_USERNAME"],
        "aud": os.environ["SF_LOGIN_URL"],
        "exp": int(time.time()) + 300,
    }

    private_key = os.environ["SF_PRIVATE_KEY"]

    assertion = jwt.encode(payload, private_key, algorithm="RS256")

    r = requests.post(
        f"{os.environ['SF_LOGIN_URL']}/services/oauth2/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
