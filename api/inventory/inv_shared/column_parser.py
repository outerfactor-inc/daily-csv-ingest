import csv
import io
from typing import Any, Dict, Iterable, Iterator, List

# Canonical normalized inventory schema. Every distributor parser MUST emit rows
# with exactly these keys, regardless of what the distributor calls the columns.
# This is the contract that keeps inv_shared (source / upsert / ingest) fully
# distributor-agnostic.
QTY_FIELDS = ("on_hand", "available", "on_order")
REQUIRED_FIELDS = ("sku",)
KNOWN_FIELDS = REQUIRED_FIELDS + QTY_FIELDS


def col_letter_to_index(letter: str) -> int:
    """
    Convert a spreadsheet column letter to a 0-based index.
      'A' -> 0, 'B' -> 1, ... 'Z' -> 25, 'AA' -> 26
    Mapping by column letter (instead of header text) means a distributor's
    layout is changed by editing one small dict, even if they rename headers.
    """
    s = (letter or "").strip().upper()
    if not s or not s.isalpha():
        raise ValueError(f"Invalid column letter: {letter!r}")
    idx = 0
    for ch in s:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def parse_int(value: Any, default: int | None = 0) -> int | None:
    """
    Parses integers from strings like '1', ' 2 ', '1,234', ''.
    Returns default (0 by default) when blank or '-'.
    """
    if value is None:
        return default
    s = str(value).strip()
    if s == "":
        return default
    s = s.replace(",", "")
    if s == "-":
        return default
    try:
        return int(float(s))  # handles '10.0' if it ever appears
    except ValueError:
        raise ValueError(f"Invalid integer value: {value!r}")


def _resolve_column_map(column_map: Dict[str, str]) -> Dict[int, str]:
    """
    Turn a letter-keyed map ({'B': 'sku', 'F': 'available'}) into an index-keyed
    map ({1: 'sku', 5: 'available'}). Validates field names and required fields.
    """
    if not column_map:
        raise ValueError("column_map is empty — distributor column layout not configured.")

    resolved: Dict[int, str] = {}
    for letter, field in column_map.items():
        if field not in KNOWN_FIELDS:
            raise ValueError(
                f"Unknown target field {field!r} for column {letter!r}. "
                f"Allowed: {', '.join(KNOWN_FIELDS)}"
            )
        resolved[col_letter_to_index(letter)] = field

    missing_required = [f for f in REQUIRED_FIELDS if f not in resolved.values()]
    if missing_required:
        raise ValueError(
            f"column_map is missing required field(s): {', '.join(missing_required)}"
        )
    return resolved


def iter_csv_rows(csv_bytes: bytes, encoding: str = "utf-8") -> Iterator[List[str]]:
    """Yield each CSV row as a list of string cells."""
    text = csv_bytes.decode(encoding, errors="replace")
    for row in csv.reader(io.StringIO(text)):
        yield row


def iter_xls_rows(xls_bytes: bytes, sheet_index: int = 0) -> Iterator[List[str]]:
    """
    Yield each row of a legacy .xls (binary Excel) workbook as a list of string
    cells, so it feeds the same column-mapping core as CSV. Numbers stored as
    floats (e.g. 5.0) are emitted as "5" so SKU/qty parsing behaves like CSV.
    """
    import xlrd  # lazy import: only .xls distributors need it

    book = xlrd.open_workbook(file_contents=xls_bytes)
    sheet = book.sheet_by_index(sheet_index)
    for r in range(sheet.nrows):
        out: List[str] = []
        for c in range(sheet.ncols):
            v = sheet.cell_value(r, c)
            if isinstance(v, float) and v.is_integer():
                v = str(int(v))
            elif not isinstance(v, str):
                v = str(v)
            out.append(v)
        yield out


def parse_inventory_rows(
    row_iter: Iterable[List[Any]],
    column_map: Dict[str, str],
    *,
    has_header: bool = True,
    skip_rows: int = 0,
) -> Dict[str, Any]:
    """
    Position-based inventory parsing core, shared by all distributors and all
    file formats. Operates on an iterable of rows (each a list of cells) so the
    row source (CSV, XLS, ...) is decoupled from the mapping/normalization/filter.

    column_map : letter -> canonical field, e.g. {'B': 'sku', 'F': 'available',
                 'G': 'on_hand', 'H': 'on_order'}. Any column not listed is ignored.
    skip_rows  : number of leading rows to discard before parsing (e.g. preamble
                 / garbage rows some exports put above the data). Applied first.
    has_header : skip one header row immediately after the skipped rows when True.

    Returns {"rows": [...normalized...], "summary": {...}}.
    Rows are kept only when at least one quantity (available / on_hand / on_order)
    is greater than 0.
    """
    index_map = _resolve_column_map(column_map)
    max_index = max(index_map)

    rows: List[Dict[str, Any]] = []
    total_rows = 0
    skipped = 0
    skipped_zero_qty = 0
    errors: List[str] = []

    for i, raw in enumerate(row_iter, start=1):
        if i <= skip_rows:
            continue  # leading preamble / garbage rows
        if has_header and i == skip_rows + 1:
            continue  # header row (sits right after the skipped rows)
        if not raw or all((c or "").strip() == "" for c in raw):
            continue  # blank line

        total_rows += 1
        try:
            if len(raw) <= max_index:
                # Row is too short to contain all mapped columns.
                skipped += 1
                errors.append(f"Row {i}: only {len(raw)} columns, need at least {max_index + 1}")
                continue

            record: Dict[str, Any] = {}
            for idx, field in index_map.items():
                cell = raw[idx]
                cell = cell.strip() if isinstance(cell, str) else cell
                if field == "sku":
                    record["sku"] = (cell or "").strip()
                else:
                    record[field] = parse_int(cell, default=0)

            # Fill any qty field not present in the map with 0.
            for q in QTY_FIELDS:
                record.setdefault(q, 0)

            if not record["sku"]:
                skipped += 1
                continue

            if not (record["available"] > 0 or record["on_hand"] > 0 or record["on_order"] > 0):
                skipped += 1
                skipped_zero_qty += 1
                continue

            rows.append({
                "sku": record["sku"],
                "on_hand": record["on_hand"],
                "available": record["available"],
                "on_order": record["on_order"],
            })

        except Exception as e:
            skipped += 1
            errors.append(f"Row {i}: {e}")

    summary = {
        "total_rows": total_rows,
        "kept": len(rows),
        "skipped": skipped,
        "skipped_zero_qty": skipped_zero_qty,
        "column_map": column_map,
        "has_header": has_header,
        "skip_rows": skip_rows,
        "errors_preview": errors[:5],
    }
    return {"rows": rows, "summary": summary}


def parse_inventory_by_columns(
    csv_bytes: bytes,
    column_map: Dict[str, str],
    *,
    has_header: bool = True,
    skip_rows: int = 0,
    encoding: str = "utf-8",
) -> Dict[str, Any]:
    """Parse a CSV inventory export by column position. See parse_inventory_rows."""
    return parse_inventory_rows(
        iter_csv_rows(csv_bytes, encoding),
        column_map,
        has_header=has_header,
        skip_rows=skip_rows,
    )


def parse_inventory_xls_by_columns(
    xls_bytes: bytes,
    column_map: Dict[str, str],
    *,
    has_header: bool = True,
    skip_rows: int = 0,
    sheet_index: int = 0,
) -> Dict[str, Any]:
    """Parse a legacy .xls inventory export by column position. See parse_inventory_rows."""
    return parse_inventory_rows(
        iter_xls_rows(xls_bytes, sheet_index),
        column_map,
        has_header=has_header,
        skip_rows=skip_rows,
    )
