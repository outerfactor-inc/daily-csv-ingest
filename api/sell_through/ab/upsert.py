from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from api.shared.sf_client import sf_create, sf_query, sf_update


def parse_date(value: Any) -> Optional[str]:
    """
    Returns YYYY-MM-DD (Salesforce Date format) or None.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    try:
        return dt.date.fromisoformat(s).isoformat()
    except Exception:
        pass

    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            continue

    return None


def parse_decimal(value: Any) -> Optional[float]:
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


def _join_non_empty(*parts: Any) -> Optional[str]:
    cleaned = [str(p).strip() for p in parts if str(p or "").strip()]
    return ", ".join(cleaned) if cleaned else None


def build_sell_through_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maps one AB CSV row into Sell_Through__c fields.
    """
    return {
        "Ship_Date__c": parse_date(row.get("ship_date")),
        "Transaction_Number__c": (row.get("transaction_number") or "").strip(),
        "Bill_to_Customer__c": (row.get("bill_to_customer") or "").strip() or None,
        "CSV_Shipping_Address__c": _join_non_empty(
            row.get("ship_street"),
            row.get("ship_street2"),
            row.get("ship_attention"),
        ),
        "Ship_to_Customer__c": (
            (row.get("end_user") or row.get("ship_attention") or "").strip() or None
        ),
        "Shipping_Address__Street__s": (row.get("ship_street") or "").strip() or None,
        "Shipping_Address__City__s": (row.get("ship_city") or "").strip() or None,
        "Shipping_Address__StateCode__s": (row.get("ship_state") or "").strip() or None,
        "Shipping_Address__PostalCode__s": (row.get("ship_zip") or "").strip() or None,
        "Distributor_Customer__c": (row.get("distributor_customer") or "").strip() or None,
        "Distributor_Customer_ID__c": (row.get("distributor_customer_id") or "").strip() or None,
        "Distributor_End_User__c": (row.get("end_user") or "").strip() or None,
        "Distributor_Account__c": "001Vr00000g6JNzIAM",  # "AB Distributing" (hardcoded for AB CSV uploads)
    }


def build_sell_through_line_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    sku = (row.get("sku") or "").strip() or None
    return {
        "SKU__c": sku,
        "Quantity__c": parse_int(row.get("quantity")),
        "Unit_Cost__c": parse_decimal(row.get("unit_cost")),
        "Extended_Cost__c": parse_decimal(row.get("extended_cost")),
    }


def _escape_soql_literal(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace("'", "\\'")


def get_sell_through_id_by_transaction(
    instance_url: str,
    access_token: str,
    transaction_number: str,
) -> Optional[str]:
    tn = _escape_soql_literal(transaction_number)
    soql = f"SELECT Id FROM Sell_Through__c WHERE Transaction_Number__c = '{tn}' LIMIT 1"
    res = sf_query(instance_url, access_token, soql)
    recs = res.get("records", [])
    return recs[0]["Id"] if recs else None


def get_product_id_by_sku(
    instance_url: str,
    access_token: str,
    sku: str,
) -> Optional[str]:
    sku = (sku or "").strip()
    if not sku:
        return None
    s = _escape_soql_literal(sku)
    soql = f"SELECT Id FROM Product2 WHERE StockKeepingUnit = '{s}' LIMIT 1"
    res = sf_query(instance_url, access_token, soql)
    recs = res.get("records", [])
    return recs[0]["Id"] if recs else None


def get_line_id_by_parent_and_sku(
    instance_url: str,
    access_token: str,
    sell_through_id: str,
    sku: str,
) -> Optional[str]:
    s = _escape_soql_literal(sku)
    q = (
        "SELECT Id FROM Sell_Through_Line__c "
        f"WHERE Sell_Through__c = '{sell_through_id}' AND SKU__c = '{s}' "
        "LIMIT 1"
    )
    res = sf_query(instance_url, access_token, q)
    recs = res.get("records", [])
    return recs[0]["Id"] if recs else None


def upsert_sell_through(
    instance_url: str,
    access_token: str,
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    tn = (fields.get("Transaction_Number__c") or "").strip()
    if not tn:
        raise ValueError("Sell_Through row missing Transaction_Number__c")

    existing_id = get_sell_through_id_by_transaction(instance_url, access_token, tn)
    payload = {k: v for k, v in fields.items() if v is not None}

    if existing_id:
        sf_update(instance_url, access_token, "Sell_Through__c", existing_id, payload)
        return {"id": existing_id, "action": "updated"}

    created = sf_create(instance_url, access_token, "Sell_Through__c", payload)
    return {"id": created["id"], "action": "created"}


def upsert_sell_through_line(
    instance_url: str,
    access_token: str,
    sell_through_id: str,
    sku: str,
    product_id: Optional[str],
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    sku = (sku or "").strip()
    if not sku:
        raise ValueError("Missing sku for sell through line")

    existing_id = get_line_id_by_parent_and_sku(
        instance_url, access_token, sell_through_id, sku
    )

    if existing_id:
        update_payload = {
            "Quantity__c": fields.get("Quantity__c"),
            "Unit_Cost__c": fields.get("Unit_Cost__c"),
            "Extended_Cost__c": fields.get("Extended_Cost__c"),
        }
        update_payload = {k: v for k, v in update_payload.items() if v is not None}
        sf_update(
            instance_url,
            access_token,
            "Sell_Through_Line__c",
            existing_id,
            update_payload,
        )
        return {"id": existing_id, "action": "updated"}

    create_payload = {k: v for k, v in fields.items() if v is not None}
    create_payload["Sell_Through__c"] = sell_through_id
    create_payload["SKU__c"] = sku
    if product_id:
        create_payload["Product__c"] = product_id

    created = sf_create(instance_url, access_token, "Sell_Through_Line__c", create_payload)
    return {"id": created["id"], "action": "created"}


def upsert_transaction_group(
    instance_url: str,
    access_token: str,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not rows:
        return {"ok": True, "note": "No rows"}

    parent_fields = build_sell_through_fields(rows[0])
    tn = parent_fields.get("Transaction_Number__c")

    try:
        parent_result = upsert_sell_through(instance_url, access_token, parent_fields)
        parent_id = parent_result["id"]
    except Exception as e:
        return {
            "ok": False,
            "transaction_number": tn,
            "error": str(e),
            "note": "Parent upsert failed; all lines skipped",
        }

    created = updated = skipped = errors = 0
    error_preview = []
    line_results = []

    for r in rows:
        try:
            sku = (r.get("sku") or "").strip()
            if not sku:
                skipped += 1
                continue

            product_id = get_product_id_by_sku(instance_url, access_token, sku)
            line_fields = build_sell_through_line_fields(r)
            lr = upsert_sell_through_line(
                instance_url, access_token, parent_id, sku, product_id, line_fields
            )

            line_results.append({"sku": sku, **lr})
            if lr["action"] == "created":
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors += 1
            if len(error_preview) < 5:
                error_preview.append(
                    {"transaction": tn, "sku": r.get("sku"), "error": str(e)}
                )

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
