from api.shared.sf_client import sf_query, sf_create, sf_update

def upsert_inventory_row(instance_url: str, access_token: str, sku: str, location_name: str,
                         on_hand: int, available: int, on_order: int):
    # 1) Find Product2 by StockKeepingUnit (SKU)
    sku_escaped = sku.replace("'", "\\'")
    soql_product = f"SELECT Id, StockKeepingUnit FROM Product2 WHERE StockKeepingUnit = '{sku_escaped}' LIMIT 1"
    prod_res = sf_query(instance_url, access_token, soql_product)

    if not prod_res.get("records"):
        return {"action": "skipped", "reason": "Product not found for SKU", "sku": sku, "location": location_name}

    product_id = prod_res["records"][0]["Id"]

    # 2) Find Inventory__c for (Product__c + Location_Name__c)
    loc_escaped = location_name.replace("'", "\\'")
    soql_inv = (
        "SELECT Id, Product__c, Location_Name__c "
        f"FROM Inventory__c WHERE Product__c = '{product_id}' AND Location_Name__c = '{loc_escaped}' LIMIT 1"
    )
    inv_res = sf_query(instance_url, access_token, soql_inv)

    payload = {
        "Product__c": product_id,
        "Location_Name__c": location_name,
        "On_Hand__c": on_hand,
        "Available__c": available,
        "On_Order__c": on_order,
    }

    if inv_res.get("records"):
        inv_id = inv_res["records"][0]["Id"]
        upd = sf_update(instance_url, access_token, "Inventory__c", inv_id, payload)
        return {"action": "updated", "inventoryId": inv_id, "sku": sku, "location": location_name, "result": upd}

    created = sf_create(instance_url, access_token, "Inventory__c", payload)
    return {"action": "created", "inventoryId": created.get("id"), "sku": sku, "location": location_name, "result": created}
