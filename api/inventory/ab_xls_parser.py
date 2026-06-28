import xlrd

# AB inventory .xls layout (positional, no header):
#   - first 8 rows are junk/preamble
#   - column A (index 0) = SKU, prefixed with "OF-" which we strip
#   - column I (index 8) = On Hand
#   - no Available / On Order columns (default to 0)
SKIP_ROWS = 8
SKU_COL = 0       # column A
ON_HAND_COL = 8   # column I
OF_PREFIX = "OF-"


def _cell_str(v) -> str:
    """Coerce an xlrd cell value to a string; integer-valued floats -> '5' not '5.0'."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if not isinstance(v, str):
        return str(v)
    return v


def _parse_int(value, default: int = 0) -> int:
    if value is None:
        return default
    s = str(value).strip()
    if s == "" or s == "-":
        return default
    s = s.replace(",", "")
    try:
        return int(float(s))  # handles '10.0' if it ever appears
    except ValueError:
        raise ValueError(f"Invalid integer value: {value!r}")


def _normalize_sku(raw_sku: str) -> str:
    s = (raw_sku or "").strip()
    if s.upper().startswith(OF_PREFIX):
        s = s[len(OF_PREFIX):].strip()
    return s


def parse_ab_inventory_xls(xls_bytes: bytes) -> dict:
    """
    Parse AB's inventory .xls into normalized rows matching the 3Eye parser shape:
      {"rows": [{"sku","on_hand","available","on_order"}], "summary": {...}}
    Only rows with on_hand > 0 are kept (available/on_order are always 0 for AB).
    """
    book = xlrd.open_workbook(file_contents=xls_bytes)
    sheet = book.sheet_by_index(0)

    rows = []
    total_rows = 0
    skipped = 0
    skipped_zero_qty = 0
    errors = []

    for r in range(sheet.nrows):
        if r < SKIP_ROWS:
            continue  # preamble / junk rows

        raw = [sheet.cell_value(r, c) for c in range(sheet.ncols)]
        if not raw or all(_cell_str(c).strip() == "" for c in raw):
            continue  # blank line

        total_rows += 1
        try:
            if len(raw) <= ON_HAND_COL:
                skipped += 1
                errors.append(f"Row {r + 1}: only {len(raw)} columns, need at least {ON_HAND_COL + 1}")
                continue

            sku = _normalize_sku(_cell_str(raw[SKU_COL]))
            on_hand = _parse_int(_cell_str(raw[ON_HAND_COL]), default=0)
            available = 0
            on_order = 0

            if not sku:
                skipped += 1
                continue

            if not (available > 0 or on_hand > 0 or on_order > 0):
                skipped += 1
                skipped_zero_qty += 1
                continue

            rows.append({
                "sku": sku,
                "on_hand": on_hand,
                "available": available,
                "on_order": on_order,
            })

        except Exception as e:
            skipped += 1
            errors.append(f"Row {r + 1}: {e}")

    summary = {
        "total_rows": total_rows,
        "kept": len(rows),
        "skipped": skipped,
        "skipped_zero_qty": skipped_zero_qty,
        "errors_preview": errors[:5],
    }
    return {"rows": rows, "summary": summary}
