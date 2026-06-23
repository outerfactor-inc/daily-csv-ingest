from api.inventory.inv_shared.ingest_handler import make_inventory_handler
from api.inventory.three_eye.email_filter import get_filters
from api.inventory.three_eye.csv_parser import parse_inventory_csv

# Vercel endpoint: /api/inventory/three_eye/ingest
handler = make_inventory_handler(
    get_filters=get_filters,
    parser_fn=parse_inventory_csv,
    location_env="THREE_EYE_LOCATION",
    location_default="3EyeWarehouse",
    distributor_label="3Eye",
    require_secret=True,
)
