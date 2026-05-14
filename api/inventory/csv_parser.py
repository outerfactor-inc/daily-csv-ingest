import csv
import io
import re
from typing import Any, Dict, List, Tuple


def normalize_header(h: str) -> str:
    """
    Convert CSV header to a stable snake_case key.
    Examples:
      'Part #' -> 'part'
      'On Hand' -> 'on_hand'
    """
    h = (h or "").strip().lower()
    # Replace non-alphanum with underscore
    h = re.sub(r"[^a-z0-9]+", "_", h)
    # Remove leading/trailing underscores
    h = h.strip("_")
    return h


def parse_int(value: Any, default: int | None = 0) -> int | None:
    """
    Parses integers from strings like '1', ' 2 ', '1,234', ''.
    Returns default (0 by default) when blank.
    """
    if value is None:
        return default
    s = str(value).strip()
    if s == "":
        return default
    s = s.replace(",", "")
    # Some exports use '-' to mean 0
    if s == "-":
        return default
    try:
        return int(float(s))  # handles '10.0' if it ever appears
    except ValueError:
        raise ValueError(f"Invalid integer value: {value!r}")


def parse_inventory_csv(csv_bytes: bytes, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Step 1: Normalize headers
    Step 2: Parse rows and type-cast qty fields to integers; text fields trimmed.
    Returns dict with rows + summary for debugging.
    """
    text = csv_bytes.decode(encoding, errors="replace")
    f = io.StringIO(text)

    reader = csv.DictReader(f)
    if reader.fieldnames is None:
        return {"rows": [], "summary": {"total_rows": 0, "kept": 0, "skipped": 0, "reason": "No headers"}}

    # Map original headers -> normalized headers
    header_map = {orig: normalize_header(orig) for orig in reader.fieldnames}

    rows: List[Dict[str, Any]] = []
    skipped = 0
    errors: List[str] = []

    for i, raw in enumerate(reader, start=1):
        try:
            # Normalize keys
            norm = {header_map[k]: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}

            # Required field: Part # -> sku
            sku = (norm.get("part") or "").strip()
            if not sku:
                skipped += 1
                continue

            rows.append({
                "sku": sku,
                "on_hand": parse_int(norm.get("on_hand"), default=0),
                "available": parse_int(norm.get("available"), default=0),
                "on_order": parse_int(norm.get("on_order"), default=0),
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
