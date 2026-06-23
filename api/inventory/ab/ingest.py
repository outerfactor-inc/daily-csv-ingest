from api.inventory.inv_shared.ingest_handler import make_inventory_handler
from api.inventory.ab.email_filter import get_filters
from api.inventory.ab.xls_parser import parse_inventory_xls

# Vercel endpoint: /api/inventory/ab/ingest
# NOTE: not yet on a cron. AB sends a .xls workbook (see ab/xls_parser.py); the
# AB email env vars (ab/email_filter.py) must be set before enabling writes.
# AB_LOCATION should be set to AB's Salesforce Location_Name__c.
handler = make_inventory_handler(
    get_filters=get_filters,
    parser_fn=parse_inventory_xls,
    location_env="ABWarehouse",
    location_default="ABWarehouse",
    distributor_label="AB",
    require_secret=True,
)
