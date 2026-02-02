import csv
import io
from typing import Dict, Any, List


def parse_sell_through_csv(csv_bytes: bytes) -> Dict[str, Any]:
    text = csv_bytes.decode("utf-8", errors="replace")
    f = io.StringIO(text)

    reader = csv.DictReader(f)
    rows: List[Dict[str, Any]] = []
    skipped = 0

    for raw in reader:
        try:
            txn = (raw.get("Transaction Number") or "").strip()
            sku = (raw.get("Part Number") or "").strip()

            if not txn or not sku:
                skipped += 1
                continue

            qty = int(raw.get("Quantity", 0))
            unit_cost = float(raw.get("Unit Cost", 0))
            ext_cost = qty * unit_cost

            rows.append({
                "transaction_number": txn,
                "sku": sku,
                "quantity": qty,
                "unit_cost": unit_cost,
                "extended_cost": ext_cost,
            })
        except Exception:
            skipped += 1

    return {
        "rows": rows,
        "summary": {
            "total": len(rows) + skipped,
            "kept": len(rows),
            "skipped": skipped,
        }
    }
