from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from api.shared.sf_client import sf_create, sf_query, sf_update


def parse_date(value: Any) -> Optional[str]:
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


def _in_clause(values: list[str]) -> str:
    return ", ".join("'" + _escape_soql_literal(v) + "'" for v in values)


def _chunked(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


# ---------------------------------------------------------------------------
# Batch lookup helpers — replace per-row SOQL with single IN queries
# ---------------------------------------------------------------------------

def batch_get_sell_through_ids(
    instance_url: str,
    access_token: str,
    transaction_numbers: list[str],
) -> Dict[str, str]:
    """Returns {transaction_number: sf_id} for all that already exist."""
    result: Dict[str, str] = {}
    for chunk in _chunked(transaction_numbers, 200):
        soql = (
            "SELECT Id, Transaction_Number__c FROM Sell_Through__c "
            f"WHERE Transaction_Number__c IN ({_in_clause(chunk)})"
        )
        for rec in sf_query(instance_url, access_token, soql).get("records", []):
            result[rec["Transaction_Number__c"]] = rec["Id"]
    return result


def batch_get_product_ids(
    instance_url: str,
    access_token: str,
    skus: list[str],
) -> Dict[str, str]:
    """Returns {sku: product_id} for all matching Product2 records."""
    result: Dict[str, str] = {}
    for chunk in _chunked(skus, 200):
        soql = (
            "SELECT Id, StockKeepingUnit FROM Product2 "
            f"WHERE StockKeepingUnit IN ({_in_clause(chunk)})"
        )
        for rec in sf_query(instance_url, access_token, soql).get("records", []):
            result[rec["StockKeepingUnit"]] = rec["Id"]
    return result


def batch_get_line_ids(
    instance_url: str,
    access_token: str,
    parent_ids: list[str],
) -> Dict[tuple, str]:
    """Returns {(sell_through_id, sku): line_id} for all existing lines."""
    result: Dict[tuple, str] = {}
    for chunk in _chunked(parent_ids, 200):
        soql = (
            "SELECT Id, Sell_Through__c, SKU__c FROM Sell_Through_Line__c "
            f"WHERE Sell_Through__c IN ({_in_clause(chunk)})"
        )
        for rec in sf_query(instance_url, access_token, soql).get("records", []):
            result[(rec["Sell_Through__c"], rec["SKU__c"])] = rec["Id"]
    return result


# ---------------------------------------------------------------------------
# Main batch upsert — 3 bulk lookups instead of N per-row lookups
# ---------------------------------------------------------------------------

def upsert_all_transaction_groups(
    instance_url: str,
    access_token: str,
    groups: Dict[str, List[Dict[str, Any]]],
    tx_keys: Optional[List[str]] = None,
) -> tuple[list, list]:
    """
    Upsert all transaction groups with batched SOQL lookups.
    Returns (results, tx_errors) matching the shape of upsert_transaction_group.
    """
    if tx_keys is None:
        tx_keys = list(groups.keys())

    # 1. Batch lookup: which transactions already exist?
    existing_parents = batch_get_sell_through_ids(instance_url, access_token, tx_keys)

    # 2. Batch lookup: which SKUs have a Product2 record?
    all_skus = sorted({
        (r.get("sku") or "").strip()
        for rows in groups.values()
        for r in rows
        if (r.get("sku") or "").strip()
    })
    product_map = batch_get_product_ids(instance_url, access_token, all_skus) if all_skus else {}

    # 3. Create / update parent Sell_Through__c records
    results: list = []
    tx_errors: list = []
    parent_id_map: Dict[str, str] = {}  # tn -> sf id

    for tn in tx_keys:
        rows = groups[tn]
        parent_fields = build_sell_through_fields(rows[0])
        payload = {k: v for k, v in parent_fields.items() if v is not None}
        try:
            if tn in existing_parents:
                existing_id = existing_parents[tn]
                sf_update(instance_url, access_token, "Sell_Through__c", existing_id, payload)
                parent_id_map[tn] = existing_id
                parent_result = {"id": existing_id, "action": "updated"}
            else:
                created = sf_create(instance_url, access_token, "Sell_Through__c", payload)
                parent_id_map[tn] = created["id"]
                parent_result = {"id": created["id"], "action": "created"}

            results.append({
                "ok": True,
                "transaction_number": tn,
                "sell_through": parent_result,
                "lines": None,  # filled in below
                "line_results_preview": [],
            })
        except Exception as e:
            tx_errors.append({"transaction_number": tn, "error": str(e)})

    # 4. Batch lookup: which lines already exist under the known parent IDs?
    existing_lines = (
        batch_get_line_ids(instance_url, access_token, list(parent_id_map.values()))
        if parent_id_map
        else {}
    )

    # 5. Create / update Sell_Through_Line__c records
    result_by_tn: Dict[str, dict] = {r["transaction_number"]: r for r in results}

    for tn in tx_keys:
        parent_id = parent_id_map.get(tn)
        if not parent_id:
            continue

        rows = groups[tn]
        created = updated = skipped = errors = 0
        error_preview: list = []
        line_results_preview: list = []

        for r in rows:
            sku = (r.get("sku") or "").strip()
            if not sku:
                skipped += 1
                continue

            product_id = product_map.get(sku)
            line_fields = build_sell_through_line_fields(r)
            line_key = (parent_id, sku)

            try:
                if line_key in existing_lines:
                    line_id = existing_lines[line_key]
                    update_payload = {k: v for k, v in line_fields.items() if v is not None}
                    sf_update(
                        instance_url, access_token,
                        "Sell_Through_Line__c", line_id, update_payload,
                    )
                    lr = {"id": line_id, "action": "updated"}
                    updated += 1
                else:
                    create_payload = {k: v for k, v in line_fields.items() if v is not None}
                    create_payload["Sell_Through__c"] = parent_id
                    create_payload["SKU__c"] = sku
                    if product_id:
                        create_payload["Product__c"] = product_id
                    created_rec = sf_create(
                        instance_url, access_token, "Sell_Through_Line__c", create_payload
                    )
                    lr = {"id": created_rec["id"], "action": "created"}
                    created += 1

                if len(line_results_preview) < 5:
                    line_results_preview.append({"sku": sku, **lr})
            except Exception as e:
                errors += 1
                if len(error_preview) < 5:
                    error_preview.append({"transaction": tn, "sku": sku, "error": str(e)})

        entry = result_by_tn.get(tn)
        if entry:
            entry["lines"] = {
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "errors": errors,
                "error_preview": error_preview,
            }
            entry["line_results_preview"] = line_results_preview

    return results, tx_errors


# ---------------------------------------------------------------------------
# Single-transaction upsert (kept for reference / small ad-hoc calls)
# ---------------------------------------------------------------------------

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
            instance_url, access_token,
            "Sell_Through_Line__c", existing_id, update_payload,
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
