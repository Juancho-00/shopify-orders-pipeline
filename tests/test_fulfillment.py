import json

import responses

from shopify_pipeline.shopify.fulfillment import (
    FULFILLMENT_KEY,
    BodegaEnricher,
    fetch_fulfillment_orders,
    location_by_line_item,
)
from tests.conftest import BASE, FIXTURES

ORDER_ID = 18931603603821
FO_URL = f"{BASE}/orders/{ORDER_ID}/fulfillment_orders.json"


def _fo_payload():
    return json.loads((FIXTURES / "fulfillment_orders_1006.json").read_text(encoding="utf-8"))


@responses.activate
def test_fetch_guarda_solo_lo_necesario(client):
    responses.get(FO_URL, json=_fo_payload())
    fos = fetch_fulfillment_orders(client, ORDER_ID)
    assert fos[0]["assigned_location"] == {"location_id": 80001, "name": "Bodega Principal Medellín"}
    assert "destination" not in fos[0]  # Dirección del cliente: no se duplica


def test_location_map_ignora_canceladas_y_movidas():
    fos = [
        {"status": "closed", "assigned_location": {"location_id": 1, "name": "A"},
         "line_items": [{"line_item_id": 10, "quantity": 0}]},
        {"status": "open", "assigned_location": {"location_id": 2, "name": "B"},
         "line_items": [{"line_item_id": 10, "quantity": 1}]},
        {"status": "cancelled", "assigned_location": {"location_id": 3, "name": "C"},
         "line_items": [{"line_item_id": 11, "quantity": 1}]},
    ]  # fmt: skip
    assert location_by_line_item(fos) == {10: (2, "B")}


@responses.activate
def test_enricher_agrega_bodegas(client):
    responses.get(FO_URL, json=_fo_payload())
    enricher = BodegaEnricher(client)
    orders = list(enricher.enrich([{"id": ORDER_ID}]))
    assert FULFILLMENT_KEY in orders[0]
    assert enricher.enriched == 1


@responses.activate
def test_enricher_sin_scope_continua_sin_bodega(client, caplog):
    responses.get(f"{BASE}/orders/1/fulfillment_orders.json", status=403)
    enricher = BodegaEnricher(client)
    orders = list(enricher.enrich([{"id": 1}, {"id": 2}]))

    assert len(orders) == 2
    assert all(FULFILLMENT_KEY not in o for o in orders)
    assert len(responses.calls) == 1  # Tras el 403 deja de consultar
    assert "read_merchant_managed_fulfillment_orders" in caplog.text
