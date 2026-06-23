from typing import Any, Dict
from api.inventory.inv_shared.column_parser import parse_inventory_xls_by_columns

# ---------------------------------------------------------------------------
# AB sends a legacy .xls (binary Excel) workbook, NOT a CSV (3Eye sends CSV).
# Map spreadsheet column LETTERS to the canonical fields below. Any column not
# listed here is ignored. Required: at least "sku" plus the qty columns AB sends.
# Allowed target fields: sku, available, on_hand, on_order.
# To adapt to a future AB layout change, edit ONLY the values in this file.
# ---------------------------------------------------------------------------

COLUMN_MAP = {
    "A": "sku",
    "I": "on_hand",
}

# AB's export has 8 garbage/preamble rows at the top, and the usable data
# (starting at row 9) has NO header row. So skip 8 rows and treat row 9 as data.
SKIP_ROWS = 8
HAS_HEADER = False

# AB prefixes our SKUs with "OF-". Strip it here so the normalized `sku` matches
# our Salesforce StockKeepingUnit. Distributor-specific SKU cleanup lives in this
# file so each distributor can handle its own prefix/suffix quirks independently.
AB_SKU_PREFIX = "OF-"


def _normalize_sku(raw_sku: str) -> str:
    s = (raw_sku or "").strip()
    if s.upper().startswith(AB_SKU_PREFIX.upper()):
        s = s[len(AB_SKU_PREFIX):].strip()
    return s


def parse_inventory_xls(file_bytes: bytes) -> Dict[str, Any]:
    parsed = parse_inventory_xls_by_columns(
        file_bytes,
        COLUMN_MAP,
        has_header=HAS_HEADER,
        skip_rows=SKIP_ROWS,
    )
    # Normalize AB's "OF-"-prefixed SKUs into our canonical SKU.
    for row in parsed.get("rows", []):
        row["sku"] = _normalize_sku(row["sku"])
    return parsed
