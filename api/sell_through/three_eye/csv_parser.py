import csv
import io
import re
from typing import Any, Dict, List


def _norm_header(h: str) -> str:
    h = (h or "").strip().lower()
    h = re.sub(r"[^a-z0-9]+", "_", h).strip("_")
    return h


def _to_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    s = str(v).strip().replace(",", "")
    if s == "" or s == "-":
        return default
    return int(float(s))


def _to_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    s = str(v).strip().replace(",", "")
    if s == "" or s == "-":
        return default
    return float(s)


def parse_sell_through_csv_3e(csv_bytes: bytes, encoding: str = "utf-8") -> Dict[str, Any]:
    text = csv_bytes.decode(encoding, errors="replace")
    f = io.StringIO(text)

    reader = csv.DictReader(f)
    if not reader.fieldnames:
        return {"rows": [], "summary": {"total_rows": 0, "kept": 0, "skipped": 0, "reason": "No headers"}}

    header_map = {h: _norm_header(h) for h in reader.fieldnames}

    rows: List[Dict[str, Any]] = []
    skipped = 0
    errors: List[str] = []

    for i, raw in enumerate(reader, start=1):
        try:
            rec = {header_map[k]: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}

            # TODO: update these once you confirm 3E column names
            txn = (rec.get("transaction_number") or rec.get("transaction") or "").strip()
            sku = (rec.get("sku") or rec.get("part_number") or "").strip()

            if not txn or not sku:
                skipped += 1
                continue

            qty = _to_int(rec.get("quantity"), default=0)
            unit_cost = _to_float(rec.get("unit_cost"), default=0.0)

            # If CSV has extended_cost, use it; else compute
            ext = rec.get("extended_cost")
            extended_cost = _to_float(ext, default=qty * unit_cost) if ext is not None else (qty * unit_cost)

            rows.append(
                {
                    "transaction_number": txn,
                    "sku": sku,
                    "quantity": qty,
                    "unit_cost": unit_cost,
                    "extended_cost": extended_cost,
                }
            )

        except Exception as e:
            skipped += 1
            errors.append(f"Row {i}: {e}")

    return {
        "rows": rows,
        "summary": {
            "total_rows": (reader.line_num - 1) if reader.line_num else 0,
            "kept": len(rows),
            "skipped": skipped,
            "normalized_headers": header_map,
            "errors_preview": errors[:5],
        },
    }
