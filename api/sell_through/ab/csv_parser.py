import csv
import io
import re
from typing import Any, Dict, List

def normalize_header(h: str) -> str:
    h = (h or "").strip().lower()
    h = re.sub(r"[^a-z0-9]+", "_", h).strip("_")
    return h

def parse_int(v: Any) -> int | None:
    if v is None: return None
    s = str(v).strip().replace(",", "")
    if not s: return None
    return int(float(s))

def parse_decimal(v: Any) -> float | None:
    if v is None: return None
    s = str(v).strip().replace("$", "").replace(",", "")
    if not s: return None
    return float(s)

def parse_ab_sell_through_csv(csv_bytes: bytes, encoding: str = "utf-8") -> Dict[str, Any]:
    text = csv_bytes.decode(encoding, errors="replace")
    f = io.StringIO(text)
    reader = csv.reader(f)

    rows_out: List[Dict[str, Any]] = []
    skipped = 0
    errors: List[str] = []

    # Read first row to decide if header or data
    first = next(reader, None)
    if first is None:
        return {"rows": [], "summary": {"total_rows": 0, "kept": 0, "skipped": 0, "reason": "Empty file"}}

    # If it looks like a header row, use DictReader from scratch
    looks_like_header = any("transaction" in (c or "").lower() for c in first)
    f.seek(0)

    if looks_like_header:
        dict_reader = csv.DictReader(f)
        fieldnames = dict_reader.fieldnames or []
        header_map = {h: normalize_header(h) for h in fieldnames}

        for i, raw in enumerate(dict_reader, start=1):
            try:
                rec = {header_map[k]: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}

                # Normalize to the keys we want (AB-specific canonical keys)
                out = {
                    "transaction_number": (rec.get("transaction_number") or "").strip(),
                    "sku": (rec.get("product_sku") or rec.get("sku") or "").strip(),
                    "quantity": parse_int(rec.get("quantity")),
                    "ship_date": (rec.get("ship_date") or "").strip(),
                    "unit_cost": parse_decimal(rec.get("unit_cost")),
                    "extended_cost": parse_decimal(rec.get("extended_cost")),

                    "distributor_customer": (rec.get("distributor_customer") or "").strip(),
                    "distributor_customer_id": (rec.get("distributor_customer_id") or "").strip(),
                    "end_user": (rec.get("distributor_end_user") or rec.get("end_user") or "").strip(),
                    "bill_to_customer": (rec.get("bill_to_customer") or "").strip(),

                    "ship_street": (rec.get("shipping_address_street") or rec.get("ship_street") or "").strip(),
                    "ship_street2": (rec.get("shipping_address_street_2") or rec.get("ship_street2") or "").strip(),
                    "ship_attention": (rec.get("attention") or "").strip(),
                    "ship_city": (rec.get("city") or rec.get("ship_city") or "").strip(),
                    "ship_state": (rec.get("state") or rec.get("ship_state") or "").strip(),
                    "ship_zip": (rec.get("zip") or rec.get("ship_zip") or "").strip(),
                }

                if not out["transaction_number"] or not out["sku"]:
                    skipped += 1
                    continue

                rows_out.append(out)
            except Exception as e:
                skipped += 1
                errors.append(f"Row {i}: {e}")

        summary = {
            "total_rows": dict_reader.line_num - 1 if dict_reader.line_num else 0,
            "kept": len(rows_out),
            "skipped": skipped,
            "normalized_headers": header_map,
            "errors_preview": errors[:5],
        }
        return {"rows": rows_out, "summary": summary}

    # Otherwise: positional CSV (your 1..18 list)
    for i, cols in enumerate(reader, start=1):
        try:
            # pad to length 18
            cols = (cols + [""] * 18)[:18]

            out = {
                "distributor_customer": cols[0].strip(),
                "ship_street": cols[1].strip(),
                "ship_street2": cols[2].strip(),
                "ship_attention": cols[3].strip(),
                "ship_city": cols[4].strip(),
                "ship_state": cols[5].strip(),
                "ship_zip": cols[6].strip(),
                "sku": cols[7].strip(),          # product sku
                # cols[8] ignored
                "quantity": parse_int(cols[9]),
                "ship_date": cols[10].strip(),
                "unit_cost": parse_decimal(cols[11]),
                "transaction_number": cols[12].strip(),
                "extended_cost": parse_decimal(cols[13]),
                "distributor_customer_id": cols[14].strip(),
                # cols[15] ignored
                "end_user": cols[16].strip(),
                "bill_to_customer": cols[17].strip(),
            }

            if not out["transaction_number"] or not out["sku"]:
                skipped += 1
                continue

            rows_out.append(out)
        except Exception as e:
            skipped += 1
            errors.append(f"Row {i}: {e}")

    return {
        "rows": rows_out,
        "summary": {
            "total_rows": i if "i" in locals() else 0,
            "kept": len(rows_out),
            "skipped": skipped,
            "errors_preview": errors[:5],
            "mode": "positional",
        },
    }
