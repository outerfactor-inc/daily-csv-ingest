import csv
import io
import re
from typing import Any, Dict, List, Optional


def normalize_header(h: str) -> str:
    h = (h or "").strip().lower()
    h = re.sub(r"[^a-z0-9]+", "_", h).strip("_")
    return h


def parse_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    return int(float(s))


def parse_decimal(v: Any) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace("$", "").replace(",", "")
    if not s:
        return None
    return float(s)


def _is_xls_bytes(data: bytes) -> bool:
    return data.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1")


def _coerce_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return str(v)
    return str(v).strip()


def _read_csv_rows(data: bytes, encoding: str) -> List[List[str]]:
    text = data.decode(encoding, errors="replace")
    return [[_coerce_cell(c) for c in row] for row in csv.reader(io.StringIO(text))]


def _read_xls_rows(data: bytes) -> List[List[str]]:
    try:
        import xlrd  # type: ignore
    except ImportError as exc:
        raise RuntimeError("XLS parsing requires xlrd. Install dependencies from requirements.txt.") from exc

    wb = xlrd.open_workbook(file_contents=data)
    if wb.nsheets < 1:
        return []

    sheet = wb.sheet_by_index(0)
    rows: List[List[str]] = []
    for r in range(sheet.nrows):
        row = [_coerce_cell(v) for v in sheet.row_values(r)]
        rows.append(row)
    return rows


def _parse_rows(raw_rows: List[List[str]], source_format: str) -> Dict[str, Any]:
    rows_out: List[Dict[str, Any]] = []
    skipped = 0
    errors: List[str] = []

    if not raw_rows:
        return {"rows": [], "summary": {"total_rows": 0, "kept": 0, "skipped": 0, "reason": "Empty file", "source_format": source_format}}

    first = raw_rows[0]
    looks_like_header = any("transaction" in (c or "").lower() for c in first)

    if looks_like_header:
        header_map = {h: normalize_header(h) for h in first}
        for i, row in enumerate(raw_rows[1:], start=1):
            try:
                row = (row + [""] * len(first))[:len(first)]
                rec = {header_map[first[idx]]: row[idx] for idx in range(len(first))}

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

        return {
            "rows": rows_out,
            "summary": {
                "total_rows": max(len(raw_rows) - 1, 0),
                "kept": len(rows_out),
                "skipped": skipped,
                "normalized_headers": header_map,
                "errors_preview": errors[:5],
                "source_format": source_format,
                "mode": "header",
            },
        }

    for i, cols in enumerate(raw_rows, start=1):
        try:
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
            "total_rows": len(raw_rows),
            "kept": len(rows_out),
            "skipped": skipped,
            "errors_preview": errors[:5],
            "mode": "positional",
            "source_format": source_format,
        },
    }


def parse_ab_sell_through_csv(
    csv_bytes: bytes,
    encoding: str = "utf-8",
    attachment_name: Optional[str] = None,
) -> Dict[str, Any]:
    name = (attachment_name or "").lower()

    if name.endswith(".xls") or _is_xls_bytes(csv_bytes):
        return _parse_rows(_read_xls_rows(csv_bytes), source_format="xls")

    return _parse_rows(_read_csv_rows(csv_bytes, encoding=encoding), source_format="csv")
