from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional


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
        "Shipping_Address__City__s": (row.get("ship_city") or "").strip() or None,
        "Shipping_Address__StateCode__s": (row.get("ship_state") or "").strip() or None,
        "Shipping_Address__PostalCode__s": (row.get("ship_zip") or "").strip() or None,
        "Distributor_Customer__c": (row.get("distributor_customer") or "").strip() or None,
        "Distributor_Customer_ID__c": (row.get("distributor_customer_id") or "").strip() or None,
        "Distributor_End_User__c": (row.get("end_user") or "").strip() or None,
    }


def build_sell_through_line_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    sku = (row.get("sku") or "").strip() or None
    return {
        "SKU__c": sku,
        "Quantity__c": parse_int(row.get("quantity")),
        "Unit_Cost__c": parse_decimal(row.get("unit_cost")),
        "Extended_Cost__c": parse_decimal(row.get("extended_cost")),
    }
