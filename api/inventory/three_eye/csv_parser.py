from typing import Any, Dict
from api.inventory.inv_shared.column_parser import parse_inventory_by_columns

# 3Eye inventory CSV column layout.
# Columns A, C, D, E, I are intentionally ignored.
# To adapt to a future 3Eye export change, edit ONLY this dict.
COLUMN_MAP = {
    "B": "sku",
    "F": "available",
    "G": "on_hand",
    "H": "on_order",
}

# 3Eye exports include a header row.
HAS_HEADER = True


def parse_inventory_csv(csv_bytes: bytes, encoding: str = "utf-8") -> Dict[str, Any]:
    return parse_inventory_by_columns(
        csv_bytes,
        COLUMN_MAP,
        has_header=HAS_HEADER,
        encoding=encoding,
    )
