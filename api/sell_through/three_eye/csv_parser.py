# api/sell_through/three_eye/csv_parser.py

import csv
import io
import re
from typing import Any, Dict, List


def normalize_header(h: str) -> str:
    h = (h or "").strip().lower()
    h = re.sub(r"[^a-z0-9]+", "_", h)
    h = h.strip("_")
    return h


def parse_sell_through_3e_csv(csv_bytes: bytes, encoding: str = "utf-8") -> Dict[str, Any]:
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

            # Required fields for sell-through grouping + lines
            tn = (rec.get("transaction_number") or "").strip()
            part_number = (rec.get("part_number") or "").strip()

            if not tn:
                skipped += 1
                continue

            # Don’t force part_number required yet (some distributors might call it SKU later)
            # but for 3E it should exist:
            rec["transaction_number"] = tn
            rec["part_number"] = part_number or None

            rows.append(rec)

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
