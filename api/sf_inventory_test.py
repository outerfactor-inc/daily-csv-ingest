import os
import json
import time
import requests
import jwt
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote_plus


def _read_private_key() -> str:
    return os.environ["SF_PRIVATE_KEY"].replace("\\n", "\n")


def get_salesforce_token():
    login_url = os.environ.get("SF_LOGIN_URL", "https://login.salesforce.com").rstrip("/")
    payload = {
        "iss": os.environ["SF_CLIENT_ID"],
        "sub": os.environ["SF_USERNAME"],
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


def sf_request(instance_url, access_token, method, path, *, params=None, json_body=None):
    url = instance_url.rstrip("/") + path
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=30)
    # Helpful error payloads
    if not r.ok:
        try:
            details = r.json()
        except Exception:
            details = r.text
        raise requests.HTTPError(f"{r.status_code} {r.reason} for {url}", response=r)
    return r.json() if r.text else {}


def soql_query(instance_url, access_token, soql: str):
    return sf_request(
        instance_url,
        access_token,
        "GET",
        "/services/data/v60.0/query",
        params={"q": soql},
    )


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)

            # REQUIRED: sku passed in querystring
            sku = (qs.get("sku", [""])[0] or "").strip()
            if not sku:
                raise ValueError("Missing required query param: ?sku=10-0281300")

            # Optional qty overrides
            on_hand = int(qs.get("onHand", ["0"])[0])
            available = int(qs.get("available", ["0"])[0])
            committed = int(qs.get("committed", ["0"])[0])

            # Location from env (with fallback)
            location_name = os.environ.get("THREE_EYE_LOCATION", "3EyeWarehouse")

            # Write gate: default NO
            do_write = qs.get("writeSF", ["0"])[0] == "1"

            tok = get_salesforce_token()
            instance_url = tok["instance_url"]
            access_token = tok["access_token"]

            # 1) Find Product2 by StockKeepingUnit
            sku_escaped = sku.replace("'", "\\'")
            soql_prod = f"SELECT Id, StockKeepingUnit FROM Product2 WHERE StockKeepingUnit = '{sku_escaped}' LIMIT 1"
            prod_res = soql_query(instance_url, access_token, soql_prod)

            if prod_res.get("totalSize", 0) == 0:
                body = {
                    "ok": True,
                    "matched_product": False,
                    "message": "No Product2 found with that StockKeepingUnit (SKU).",
                    "sku": sku,
                    "location": location_name,
                    "writeSF": do_write,
                    "soql_product": soql_prod,
                }
                out = json.dumps(body, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)
                return

            product_id = prod_res["records"][0]["Id"]

            # 2) Check for existing Inventory__c
            loc_escaped = location_name.replace("'", "\\'")
            soql_inv = (
                "SELECT Id, Product__c, Location_Name__c, On_Hand__c, Available__c, Committed__c "
                f"FROM Inventory__c WHERE Product__c = '{product_id}' AND Location_Name__c = '{loc_escaped}' "
                "LIMIT 1"
            )
            inv_res = soql_query(instance_url, access_token, soql_inv)

            body = {
                "ok": True,
                "sku": sku,
                "location": location_name,
                "product_id": product_id,
                "writeSF": do_write,
                "payload_preview": {
                    "Product__c": product_id,
                    "Location_Name__c": location_name,
                    "On_Hand__c": on_hand,
                    "Available__c": available,
                    "Committed__c": committed,
                },
                "soql_product": soql_prod,
                "soql_inventory": soql_inv,
            }

            if inv_res.get("totalSize", 0) == 0:
                body["inventory_found"] = False

                if do_write:
                    created = sf_request(
                        instance_url,
                        access_token,
                        "POST",
                        "/services/data/v60.0/sobjects/Inventory__c",
                        json_body=body["payload_preview"],
                    )
                    body["action"] = "created"
                    body["result"] = created
                else:
                    body["action"] = "dry_run_create"

            else:
                body["inventory_found"] = True
                inv_id = inv_res["records"][0]["Id"]
                body["inventory_id"] = inv_id

                update_payload = {
                    "On_Hand__c": on_hand,
                    "Available__c": available,
                    "Committed__c": committed,
                }

                if do_write:
                    sf_request(
                        instance_url,
                        access_token,
                        "PATCH",
                        f"/services/data/v60.0/sobjects/Inventory__c/{inv_id}",
                        json_body=update_payload,
                    )
                    body["action"] = "updated"
                    body["result"] = {"success": True, "id": inv_id}
                else:
                    body["action"] = "dry_run_update"
                    body["update_preview"] = update_payload

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

            out = json.dumps({"ok": False, "error": str(e), "details": details}, indent=2).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        except Exception as e:
            out = json.dumps({"ok": False, "error": str(e)}, indent=2).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)
