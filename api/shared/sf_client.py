import requests
from urllib.parse import quote

API_VERSION = "v60.0"  # change if you want

def _headers(access_token: str):
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

def sf_query(instance_url: str, access_token: str, soql: str):
    url = f"{instance_url}/services/data/{API_VERSION}/query"
    r = requests.get(url, headers=_headers(access_token), params={"q": soql}, timeout=30)
    r.raise_for_status()
    return r.json()

# def sf_create(instance_url: str, access_token: str, sobject: str, payload: dict):
#     url = f"{instance_url}/services/data/{API_VERSION}/sobjects/{sobject}/"
#     r = requests.post(url, headers=_headers(access_token), json=payload, timeout=30)
#     r.raise_for_status()
#     return r.json()

def sf_create(instance_url: str, access_token: str, sobject: str, payload: dict):
    url = f"{instance_url}/services/data/{API_VERSION}/sobjects/{sobject}/"
    r = requests.post(url, headers=_headers(access_token), json=payload, timeout=30)

    if not r.ok:
        # Surface Salesforce's actual error message(s)
        try:
            details = r.json()
        except Exception:
            details = r.text
        raise Exception(f"SF create failed ({r.status_code}) on {sobject}: {details}")

    return r.json()


def sf_update(instance_url: str, access_token: str, sobject: str, record_id: str, payload: dict):
    url = f"{instance_url}/services/data/{API_VERSION}/sobjects/{sobject}/{quote(record_id)}"
    r = requests.patch(url, headers=_headers(access_token), json=payload, timeout=30)
    # PATCH often returns 204 No Content
    if r.status_code == 204:
        return {"ok": True, "status": 204}
    r.raise_for_status()
    return r.json()
