# api/sell_through/three_eye/sf_upsert.py

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple, List

from api.shared.sf_client import soql_query, sf_post, sf_patch


# ----------------------------
# parsing helpers
# ----------------------------

def parse_date(value: Any) -> Optional[str]:
    """
    Returns YYYY-MM-DD (Salesforce Date format) or None.
    Handles common CSV date formats: 2026-01-30, 1/30/2026, 01/30/26, etc.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Try ISO first
    try:
        return dt.date.fromisoformat(s).isoformat()
    except Exception:
        pass

    # Try common US formats
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            continue

    # If nothing matched, return None (or raise if you prefer strict)
    return None


def parse_decimal(value: Any) -> Optional[float]:
    """
    Returns float or None. Handles $, commas, blanks.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("$", "").replace(",", "")
    try:
        return float(Decimal(s))
    except (InvalidOperation, ValueError):
        return None


def parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", "")
    try:
        return int(float(s))
    except ValueError:
        return None


# ----------------------------
# field mapping
# ----------------------------

def build_sell_through_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maps one CSV row into Sell_Through__c fields.
    This is your mapping list, exactly.
    """
    return {
        "Ship_Date__c": parse_date(row.get("ship_date")),
        "Transaction_Number__c": (row.get("transaction_number") or "").strip(),
        "Partner_to_Distributor_PO__c": (row.get("purchase_order") or "").strip() or None,
        "Bill_to_Customer__c": (row.get("bill_to_customer_name") or "").strip() or None,

        # Billing compound address fields (as you listed)
        "Billing_Address__City__s": (row.get("billing_city") or "").strip() or None,
        "Billing_Address__StateCode__s": (row.get("billing_state_province") or "").strip() or None,

        "CSV_Shipping_Address__c": (row.get("shipping_address") or "").strip() or None,
        "Ship_to_Customer__c": (row.get("ship_to_name") or "").strip() or None,

        # Shipping compound address fields
        "Shipping_Address__City__s": (row.get("shipping_city") or "").strip() or None,
        "Shipping_Address__StateCode__s": (row.get("shipping_state_province") or "").strip() or None,
        "Shipping_Address__PostalCode__s": (row.get("shipping_zip") or "").strip() or None,

        "Distributor_Customer__c": (row.get("3eye_customer") or "").strip() or None,
        "Distributor_Customer_ID__c": (row.get("3eye_customer_id") or "").strip() or None,
        "Distributor_End_User__c": (row.get("end_user") or "").strip() or None,
        "Distributor_End_User_Id__c": (row.get("end_user_id") or "").strip() or None,
    }


def build_sell_through_line_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maps one CSV row into Sell_Through_Line__c fields (except lookups).
    Lookups will be filled in after we resolve parent + product IDs.
    """
    return {
        "Quantity__c": parse_int(row.get("quantity")),
        "Unit_Cost__c": parse_decimal(row.get("unit_cost")),
        "Extended_Cost__c": parse_decimal(row.get("extended_cost")),
    }


# ----------------------------
# SOQL / upsert functions
# ----------------------------

def get_sell_through_id_by_transaction(
    instance_url: str,
    access_token: str,
    transaction_number: str,
) -> Optional[str]:
    tn = transaction_number.replace("'", "\\'")
    q = f"SELECT Id FROM Sell_Through__c WHERE Transaction_Number__c = '{tn}' LIMIT 1"
    res = soql_query(instance_url, access_token, q)
    recs = res.get("records", [])
    return recs[0]["Id"] if recs else None


def upsert_sell_through(
    instance_url: str,
    access_token: str,
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Upsert Sell_Through__c by Transaction_Number__c (query then create/update).
    Returns { id, action }
    """
    tn = (fields.get("Transaction_Number__c") or "").strip()
    if not tn:
        raise ValueError("Sell_Through row missing Transaction_Number__c")

    existing_id = get_sell_through_id_by_transaction(instance_url, access_token, tn)

    # Clean out None values if you prefer not to overwrite fields with nulls
    payload = {k: v for k, v in fields.items() if v is not None}

    if existing_id:
        sf_patch(instance_url, access_token, f"/services/data/v59.0/sobjects/Sell_Through__c/{existing_id}", payload)
        return {"id": existing_id, "action": "updated"}

    created = sf_post(instance_url, access_token, "/services/data/v59.0/sobjects/Sell_Through__c", payload)
    return {"id": created["id"], "action": "created"}


def get_product_id_by_sku(
    instance_url: str,
    access_token: str,
    sku: str,
) -> Optional[str]:
    sku = (sku or "").strip()
    if not sku:
        return None
    s = sku.replace("'", "\\'")
    q = f"SELECT Id FROM Product2 WHERE StockKeepingUnit = '{s}' LIMIT 1"
    res = soql_query(instance_url, access_token, q)
    recs = res.get("records", [])
    return recs[0]["Id"] if recs else None


def get_line_id_by_parent_and_product(
    instance_url: str,
    access_token: str,
    sell_through_id: str,
    product_id: str,
) -> Optional[str]:
    q = (
        "SELECT Id FROM Sell_Through_Line__c "
        f"WHERE Sell_Through__c = '{sell_through_id}' AND Product__c = '{product_id}' "
        "LIMIT 1"
    )
    res = soql_query(instance_url, access_token, q)
    recs = res.get("records", [])
    return recs[0]["Id"] if recs else None


def upsert_sell_through_line(
    instance_url: str,
    access_token: str,
    sell_through_id: str,
    product_id: str,
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Upsert line by (Sell_Through__c, Product__c).
    If that pair already exists: update
    else: create
    """
    payload = {k: v for k, v in fields.items() if v is not None}
    payload["Sell_Through__c"] = sell_through_id
    payload["Product__c"] = product_id

    existing_id = get_line_id_by_parent_and_product(instance_url, access_token, sell_through_id, product_id)
    if existing_id:
        sf_patch(instance_url, access_token, f"/services/data/v59.0/sobjects/Sell_Through_Line__c/{existing_id}", payload)
        return {"id": existing_id, "action": "updated"}

    created = sf_post(instance_url, access_token, "/services/data/v59.0/sobjects/Sell_Through_Line__c", payload)
    return {"id": created["id"], "action": "created"}


def upsert_transaction_group(
    instance_url: str,
    access_token: str,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Rows must all have the same transaction_number.
    Upserts parent once, then each line.
    """
    if not rows:
        return {"ok": True, "note": "No rows"}

    parent_fields = build_sell_through_fields(rows[0])
    tn = parent_fields.get("Transaction_Number__c")

    parent_result = upsert_sell_through(instance_url, access_token, parent_fields)
    parent_id = parent_result["id"]

    created = updated = skipped = errors = 0
    error_preview = []
    line_results = []

    for r in rows:
        try:
            sku = (r.get("part_number") or "").strip()
            product_id = get_product_id_by_sku(instance_url, access_token, sku)

            if not product_id:
                skipped += 1
                if len(error_preview) < 5:
                    error_preview.append({"transaction": tn, "sku": sku, "error": "Product2 not found by StockKeepingUnit"})
                continue

            line_fields = build_sell_through_line_fields(r)
            lr = upsert_sell_through_line(instance_url, access_token, parent_id, product_id, line_fields)
            line_results.append({"sku": sku, **lr})

            if lr["action"] == "created":
                created += 1
            else:
                updated += 1

        except Exception as e:
            errors += 1
            if len(error_preview) < 5:
                error_preview.append({"transaction": tn, "sku": r.get("part_number"), "error": str(e)})

    return {
        "ok": True,
        "transaction_number": tn,
        "sell_through": parent_result,
        "lines": {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "error_preview": error_preview,
        },
        "line_results_preview": line_results[:5],
    }
