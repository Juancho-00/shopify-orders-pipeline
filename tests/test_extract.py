import json
from datetime import datetime, timezone

import pytest
import responses

from shopify_pipeline.exceptions import ConfigError
from shopify_pipeline.extract import MANIFEST_SCHEMA_VERSION, new_run_id, run_extraction
from shopify_pipeline.shopify.orders import OrderFilter
from tests.conftest import BASE


def _mock_shopify(orders_page, count):
    responses.get(f"{BASE}/orders/count.json", json={"count": count})
    responses.get(f"{BASE}/orders.json", json=orders_page)


def test_new_run_id():
    assert new_run_id(datetime(2026, 10, 13, 16, 15, 0, tzinfo=timezone.utc)) == "20261013T161500Z"


@responses.activate
def test_run_extraction_escribe_datos_y_manifiesto(client, flt, orders_page, tmp_path):
    _mock_shopify(orders_page, count=2)
    result = run_extraction(client, flt, output_dir=tmp_path, run_id="RUN1", consultar_bodega=False)

    assert result.reconciled
    assert result.written_count == 2
    assert len((tmp_path / "RUN1.jsonl").read_text(encoding="utf-8").splitlines()) == 2

    manifest = json.loads((tmp_path / "RUN1.manifest.json").read_text(encoding="utf-8"))
    assert manifest["expected_count"] == 2
    assert manifest["reconciled"] is True
    assert manifest["status_filter"] == "any"
    assert manifest["api_version"] == "2026-10"
    assert manifest["output_file"] == "RUN1.jsonl"


@responses.activate
def test_run_extraction_detecta_descuadre(client, flt, orders_page, tmp_path, caplog):
    _mock_shopify(orders_page, count=5)
    result = run_extraction(client, flt, output_dir=tmp_path, run_id="RUN2", consultar_bodega=False)

    assert not result.reconciled
    assert "Conciliación" in caplog.text
    manifest = json.loads((tmp_path / "RUN2.manifest.json").read_text(encoding="utf-8"))
    assert manifest["reconciled"] is False


@responses.activate
def test_run_extraction_consulta_bodega_por_pedido(client, flt, orders_page, tmp_path):
    _mock_shopify(orders_page, count=2)
    for order in orders_page["orders"]:
        responses.get(f"{BASE}/orders/{order['id']}/fulfillment_orders.json", json={"fulfillment_orders": []})

    result = run_extraction(client, flt, output_dir=tmp_path, run_id="RUN3")

    assert result.bodegas_consultadas == 2
    lines = (tmp_path / "RUN3.jsonl").read_text(encoding="utf-8").splitlines()
    assert all("_fulfillment_orders" in json.loads(line) for line in lines)


@responses.activate
def test_run_extraction_no_sobrescribe_una_extraccion(client, flt, orders_page, tmp_path):
    _mock_shopify(orders_page, count=2)
    run_extraction(client, flt, output_dir=tmp_path, run_id="RUN4", consultar_bodega=False)
    with pytest.raises(ConfigError, match="Ya existe"):
        run_extraction(client, flt, output_dir=tmp_path, run_id="RUN4", consultar_bodega=False)


@responses.activate
def test_manifiesto_registra_fields_y_version(client, flt, orders_page, tmp_path):
    _mock_shopify(orders_page, count=2)
    proyectado = OrderFilter(flt.date_min, flt.date_max, fields=("name",))
    run_extraction(client, proyectado, output_dir=tmp_path, run_id="RUN5", consultar_bodega=False)
    manifest = json.loads((tmp_path / "RUN5.manifest.json").read_text(encoding="utf-8"))
    assert manifest["fields"] == ["id", "name"]
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["incremental"] is False


@responses.activate
def test_pedido_que_sale_de_la_ventana_no_es_descuadre(client, flt, orders_page, tmp_path):
    """Con updated_at, un pedido modificado durante la corrida sale de la ventana."""
    responses.get(f"{BASE}/orders/count.json", json={"count": 3})  # al iniciar
    responses.get(f"{BASE}/orders/count.json", json={"count": 2})  # al terminar
    responses.get(f"{BASE}/orders.json", json=orders_page)

    result = run_extraction(client, flt, output_dir=tmp_path, run_id="RUN6", consultar_bodega=False)

    assert result.reconciled
    manifest = json.loads((tmp_path / "RUN6.manifest.json").read_text(encoding="utf-8"))
    assert (manifest["expected_count"], manifest["recount_count"], manifest["written_count"]) == (3, 2, 2)


@responses.activate
def test_descuadre_real_se_mantiene_tras_el_segundo_conteo(client, flt, orders_page, tmp_path):
    _mock_shopify(orders_page, count=3)  # Ambos conteos dicen 3, pero solo llegan 2
    result = run_extraction(client, flt, output_dir=tmp_path, run_id="RUN7", consultar_bodega=False)
    assert not result.reconciled
    assert result.recount_count == 3


@responses.activate
def test_sin_descuadre_no_hay_segundo_conteo(client, flt, orders_page, tmp_path):
    _mock_shopify(orders_page, count=2)
    result = run_extraction(client, flt, output_dir=tmp_path, run_id="RUN8", consultar_bodega=False)
    assert result.recount_count is None
    assert sum("count.json" in c.request.url for c in responses.calls) == 1
