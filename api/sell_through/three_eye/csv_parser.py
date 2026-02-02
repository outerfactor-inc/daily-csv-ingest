import csv
import io
import re
from typing import Any, Dict, List


def normalize_header(h: str) -> str:
    h = (h or "").strip().lower()
    h = re.sub(r"[^a-z0-9]+", "_", h).strip("_")
    return h


def parse_int(value: Any, default: int | None = 0) -> int | None:
    if value is None:
        return default
    s = str(value).strip()
    if s == "":
        return default
    s = s.replace(",", "")
    if s == "-":
        return default
    return int(float(s))


def parse_float(value: Any, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    s = str(value).strip()
    if s == "":
        return default
    # remove $ and commas
    s = s.replace("$", "").replace(",", "")
    if s == "-":
        return default
    return float(s)


def parse_sell_through_3e_csv(csv_bytes: bytes, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Parses 3E sell-through CSV into stable keys:
      transaction_number, sku, quantity, unit_cost, extended_cost, ship_date, etc.

    Only returns the fields we care about for SF upsert, but keeps room to expand later.
    """
    text = csv_bytes.decode(encoding, errors="replace")
    f = io.StringIO(text)
    reader = csv.DictReader(f)

    if reader.fieldnames is None:
        return {"rows": [], "summary": {"total_rows": 0, "kept": 0, "skipped": 0, "reason": "No headers"}}

    header_map = {orig: normalize_header(orig) for orig in reader.fieldnames}

    rows: List[Dict[str, Any]] = []
    skipped = 0
    errors: List[str] = []

    for i, raw in enumerate(reader, start=1):
        try:
            rec = {header_map[k]: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}

            txn = (rec.get("transaction_number") or "").strip()
            sku = (rec.get("part_number") or "").strip()

            if not txn or not sku:
                skipped += 1
                continue

            qty = parse_int(rec.get("quantity"), default=0) or 0
            unit_cost = parse_float(rec.get("unit_cost"), default=0.0) or 0.0

            # Prefer file’s Extended Cost if present; otherwise compute.
            ext_cost_raw = rec.get("extended_cost")
            if ext_cost_raw is None or str(ext_cost_raw).strip() == "":
                extended_cost = float(qty) * float(unit_cost)
            else:
                extended_cost = parse_float(ext_cost_raw, default=float(qty) * float(unit_cost)) or 0.0

            rows.append({
                "ship_date": (rec.get("ship_date") or "").strip(),
                "transaction_number": txn,
                "quantity": qty,
                "sku": sku,
                "description": (rec.get("description") or "").strip(),
                "unit_cost": unit_cost,
                "extended_cost": extended_cost,

                # keep these around for later if needed
                "purchase_order": (rec.get("purchase_order") or "").strip(),
                "bill_to_customer_name": (rec.get("bill_to_customer_name") or "").strip(),
                "shipping_city": (rec.get("shipping_city") or "").strip(),
                "shipping_state_province": (rec.get("shipping_state_province") or "").strip(),
                "shipping_zip": (rec.get("shipping_zip") or "").strip(),
                "tracking_numbers": (rec.get("tracking_numbers") or "").strip(),
                "vendor_quote": (rec.get("3e_vendor_quote") or rec.get("3e_vendor_quote_") or "").strip(),
            })

        except Exception as e:
            skipped += 1
            errors.append(f"Row {i}: {e}")

    summary = {
        "total_rows": (reader.line_num - 1) if reader.line_num else 0,
        "kept": len(rows),
        "skipped": skipped,
        "normalized_headers": header_map,
        "errors_preview": errors[:5],
    }
    return {"rows": rows, "summary": summary}
