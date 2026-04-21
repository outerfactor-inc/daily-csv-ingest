import csv
import io
import re
from typing import Any, Dict, List, Optional


def parse_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    return int(float(s))


def _is_xls_bytes(data: bytes) -> bool:
    return data.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1")


def _coerce_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
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
        row: List[str] = []
        for c in range(sheet.ncols):
            cell = sheet.cell(r, c)
            if cell.ctype == xlrd.XL_CELL_DATE:
                import datetime
                dt = xlrd.xldate_as_datetime(cell.value, wb.datemode)
                row.append(dt.strftime("%m/%d/%Y"))
            else:
                row.append(_coerce_cell(cell.value))
        rows.append(row)
    return rows


def _parse_ab_sku(raw: str) -> str:
    """Strip leading 'OF-' prefix from AB stock codes. e.g. 'OF-11-0540000' -> '11-0540000'."""
    return re.sub(r"^OF-", "", raw.strip(), flags=re.IGNORECASE)


def _is_header_row(cols: List[str]) -> bool:
    """Detect header row by checking if col 5 (ShipQty) is non-numeric."""
    val = cols[5].strip() if len(cols) > 5 else ""
    return bool(val) and not re.fullmatch(r"[\d,]+(\.\d+)?", val)


def _parse_rows(raw_rows: List[List[str]], source_format: str) -> Dict[str, Any]:
    if not raw_rows:
        return {
            "rows": [],
            "summary": {
                "total_rows": 0,
                "kept": 0,
                "skipped": 0,
                "reason": "Empty file",
                "source_format": source_format,
            },
        }

    start_idx = 0
    if _is_header_row(raw_rows[0]):
        start_idx = 1

    rows_out: List[Dict[str, Any]] = []
    skipped = 0
    errors: List[str] = []

    for i, cols in enumerate(raw_rows[start_idx:], start=start_idx + 1):
        try:
            # pad to at least 14 columns
            cols = (cols + [""] * 14)[:14]

            ab_sku = cols[3].strip()
            sku = _parse_ab_sku(ab_sku) if ab_sku else ""

            out = {
                "distributor_customer": cols[0].strip(),
                "ab_sku": ab_sku,
                "sku": sku,
                "quantity": parse_int(cols[5]),
                "end_user": cols[6].strip(),
                "ship_state": cols[8].strip(),
                "ship_zip": cols[10].strip(),
                "transaction_number": cols[13].strip(),
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
            "total_rows": max(len(raw_rows) - start_idx, 0),
            "kept": len(rows_out),
            "skipped": skipped,
            "errors_preview": errors[:5],
            "mode": "positional",
            "source_format": source_format,
        },
    }


def parse_ab_weekly_sell_through_csv(
    csv_bytes: bytes,
    encoding: str = "utf-8",
    attachment_name: Optional[str] = None,
) -> Dict[str, Any]:
    name = (attachment_name or "").lower()
    if name.endswith(".xls") or _is_xls_bytes(csv_bytes):
        return _parse_rows(_read_xls_rows(csv_bytes), source_format="xls")
    return _parse_rows(_read_csv_rows(csv_bytes, encoding=encoding), source_format="csv")
