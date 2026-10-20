"""
ExtracciÃ³n con GraphQL. Shopify se simula con ``responses``: ninguna prueba sale a internet.

La prueba clave es ``test_graphql_y_rest_dan_el_mismo_reporte``: el mismo pedido #1006,
leÃ­do por REST y por GraphQL, debe producir exactamente las mismas filas para Siesa.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest
import responses

from shopify_pipeline.config import ShopifyConfig
from shopify_pipeline.exceptions import ConfigError, ShopifyPermissionError
from shopify_pipeline.extract import run_extraction
from shopify_pipeline.shopify.client import ShopifyClient
from shopify_pipeline.shopify.fulfillment import FULFILLMENT_KEY, _slim
from shopify_pipeline.shopify.graphql_orders import (
    BODEGAS_POR_PEDIDO,
    LINEAS_POR_PAGINA,
    ORDERS_QUERY,
    EstadisticasGraphQL,
    a_formato_rest,
    count_orders_graphql,
    extract_orders_graphql,
    search_query,
    siguiente_tamano,
)
from shopify_pipeline.shopify.orders import OrderFilter
from shopify_pipeline.transform.siesa_lines import order_to_lines
from tests.conftest import BASE, FIXTURES, SHOP

URL = f"{BASE}/graphql.json"


@pytest.fixture
def gql_client(sleeps):
    config = ShopifyConfig(shop_domain=SHOP, access_token="shpat_test", max_attempts=3, api="graphql")
    return ShopifyClient(config, sleep=sleeps.append)


@pytest.fixture
def respuesta():
    return json.loads((FIXTURES / "graphql_orders_1006.json").read_text(encoding="utf-8"))


@pytest.fixture
def nodo(respuesta):
    return respuesta["data"]["orders"]["nodes"][0]


def _consulta(request) -> tuple[str, dict]:
    cuerpo = json.loads(request.body)
    return cuerpo["query"], cuerpo["variables"]


def _conteo(n):
    return {"data": {"ordersCount": {"count": n, "precision": "EXACT"}}}


# -------------------------------------------------------------- conversiÃ³n
def test_graphql_y_rest_dan_el_mismo_reporte(nodo):
    rest = json.loads((FIXTURES / "order_1006.json").read_text(encoding="utf-8"))
    fos = json.loads((FIXTURES / "fulfillment_orders_1006.json").read_text(encoding="utf-8"))
    rest[FULFILLMENT_KEY] = [_slim(fo) for fo in fos["fulfillment_orders"]]

    filas_rest = order_to_lines(rest).rows
    filas_graphql = order_to_lines(a_formato_rest(nodo)).rows
    assert len(filas_graphql) == len(filas_rest) == 2
    for fila_rest, fila_graphql in zip(filas_rest, filas_graphql, strict=True):
        diferencias = {
            k: (fila_rest[k], fila_graphql[k]) for k in fila_rest if fila_rest[k] != fila_graphql[k]
        }
        assert diferencias == {}
    assert order_to_lines(a_formato_rest(nodo)).eventos == order_to_lines(rest).eventos


def test_conversion_de_campos(nodo):
    pedido = a_formato_rest(nodo)
    assert (pedido["id"], pedido["name"], pedido["order_number"]) == (18931603603821, "#1006", 1006)
    assert pedido["financial_status"] == "pending"  # PENDING â†’ como en REST
    assert pedido["line_items"][0]["id"] == 50783188156781  # gid://shopify/LineItem/... â†’ nÃºmero
    assert pedido["line_items"][0]["price"] == "89999.0"
    assert pedido["shipping_lines"][0]["discounted_price"] == "12294.34"
    bodega = pedido[FULFILLMENT_KEY][0]
    assert bodega["status"] == "open"
    assert bodega["assigned_location"] == {"location_id": 80001, "name": "D'Luchi PT Guarne"}
    assert bodega["line_items"] == [{"line_item_id": 50783188156781, "quantity": 1}]
    assert pedido["billing_address"]["province_code"] == "ANT"


def test_conversion_de_cancelado_y_atributos(nodo):
    nodo = copy.deepcopy(nodo) | {
        "cancelledAt": "2026-10-09T15:00:00Z",
        "cancelReason": "CUSTOMER",
        "displayFinancialStatus": "PARTIALLY_REFUNDED",
        "customAttributes": [{"key": "Horario", "value": "Tarde"}],
        "customer": None,
    }
    pedido = a_formato_rest(nodo)
    assert (pedido["cancel_reason"], pedido["financial_status"]) == ("customer", "partially_refunded")
    assert pedido["note_attributes"] == [{"name": "Horario", "value": "Tarde"}]
    assert pedido["customer"] is None


# ------------------------------------------------------------------ filtro
def test_search_query():
    flt = OrderFilter(
        date_min=datetime(2026, 10, 19, 11, 0, tzinfo=timezone.utc),
        date_max=datetime(2026, 10, 20, 11, 30, tzinfo=timezone.utc),
        date_field="updated_at",
    )
    assert search_query(flt) == (
        "updated_at:>='2026-10-19T11:00:00+00:00' AND updated_at:<='2026-10-20T11:30:00+00:00'"
    )
    abiertos = OrderFilter(date_min=flt.date_min, date_max=flt.date_max, status="open")
    assert search_query(abiertos).endswith(" AND status:open")


# ---------------------------------------------------------------- consultas
@responses.activate
def test_conteo(gql_client, flt):
    responses.post(URL, json=_conteo(7))
    assert count_orders_graphql(gql_client, flt) == 7
    _, variables = _consulta(responses.calls[0].request)
    assert variables["query"].startswith("created_at:>=")


@responses.activate
def test_paginacion_por_cursor(gql_client, flt, respuesta):
    segundo = copy.deepcopy(respuesta)
    segundo["data"]["orders"]["nodes"][0] |= {
        "id": "gid://shopify/Order/2",
        "legacyResourceId": "2",
        "name": "#1007",
    }
    primera = copy.deepcopy(respuesta)
    primera["data"]["orders"]["pageInfo"] = {"hasNextPage": True, "endCursor": "CURSOR-1"}
    responses.post(URL, json=primera)
    responses.post(URL, json=segundo)

    pedidos = list(extract_orders_graphql(gql_client, flt))
    assert [p["name"] for p in pedidos] == ["#1006", "#1007"]
    _, variables = _consulta(responses.calls[1].request)
    assert variables["after"] == "CURSOR-1"


@responses.activate
def test_pedido_con_muchas_lineas_trae_el_resto(gql_client, flt, respuesta):
    respuesta["data"]["orders"]["nodes"][0]["lineItems"]["pageInfo"] = {
        "hasNextPage": True,
        "endCursor": "L1",
    }
    extra = copy.deepcopy(respuesta["data"]["orders"]["nodes"][0]["lineItems"]["nodes"][0])
    extra |= {"id": "gid://shopify/LineItem/999", "sku": "SKU-EXTRA"}
    mas = {"data": {"order": {"lineItems": {"pageInfo": {"hasNextPage": False}, "nodes": [extra]}}}}
    responses.post(URL, json=respuesta)
    responses.post(URL, json=mas)

    (pedido,) = extract_orders_graphql(gql_client, flt)
    assert [li["sku"] for li in pedido["line_items"]] == ["KITK0108", "SKU-EXTRA"]
    consulta, variables = _consulta(responses.calls[1].request)
    assert "MasLineas" in consulta and variables["after"] == "L1"


@responses.activate
def test_consulta_costosa_achica_la_pagina(gql_client, flt, respuesta):
    caro = {"errors": [{"message": "Query cost is 1500", "extensions": {"code": "MAX_COST_EXCEEDED"}}]}
    responses.post(URL, json=caro)
    responses.post(URL, json=respuesta)
    list(extract_orders_graphql(gql_client, flt, por_pagina=4))
    assert [_consulta(c.request)[1]["first"] for c in responses.calls] == [4, 2]


@responses.activate
def test_throttled_espera_y_reintenta(gql_client, flt, respuesta, sleeps):
    frenado = {
        "errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}],
        "extensions": {"cost": {"requestedQueryCost": 500, "throttleStatus": {
            "maximumAvailable": 2000, "currentlyAvailable": 100, "restoreRate": 100}}},
    }  # fmt: skip
    responses.post(URL, json=frenado)
    responses.post(URL, json=respuesta)
    assert len(list(extract_orders_graphql(gql_client, flt))) == 1
    assert sleeps[0] == pytest.approx(4.0)  # (500 - 100) / 100 puntos por segundo


@responses.activate
def test_pausa_preventiva_cuando_quedan_pocos_puntos(gql_client, flt, respuesta, sleeps):
    respuesta["extensions"]["cost"]["throttleStatus"]["currentlyAvailable"] = 200.0  # 10 % del mÃ¡ximo
    responses.post(URL, json=respuesta)
    list(extract_orders_graphql(gql_client, flt))
    assert sleeps == [pytest.approx(8.0)]  # (1000 - 200) / 100


@responses.activate
def test_acceso_denegado(gql_client, flt):
    responses.post(
        URL, json={"errors": [{"message": "Access denied", "extensions": {"code": "ACCESS_DENIED"}}]}
    )
    with pytest.raises(ShopifyPermissionError, match="read_merchant_managed_fulfillment_orders"):
        count_orders_graphql(gql_client, flt)


@responses.activate
def test_run_extraction_con_graphql(gql_client, flt, respuesta, tmp_path):
    responses.post(URL, json=_conteo(1))
    responses.post(URL, json=respuesta)
    result = run_extraction(gql_client, flt, output_dir=tmp_path, run_id="RUN1")

    assert result.reconciled and result.api == "graphql"
    assert result.bodegas_consultadas == 1
    assert len(responses.calls) == 2  # conteo + 1 pÃ¡gina: sin llamadas extra por pedido para la bodega
    (linea,) = (tmp_path / "RUN1.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(linea)[FULFILLMENT_KEY][0]["assigned_location"]["name"] == "D'Luchi PT Guarne"
    manifiesto = json.loads((tmp_path / "RUN1.manifest.json").read_text(encoding="utf-8"))
    assert manifiesto["api"] == "graphql"


def test_api_invalida():
    with pytest.raises(ConfigError, match="SHOPIFY_API"):
        ShopifyConfig(shop_domain=SHOP, access_token="x", api="soap")


def test_graphql_es_la_api_por_defecto(monkeypatch):
    monkeypatch.delenv("SHOPIFY_API")
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", SHOP)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "x")
    assert ShopifyConfig.from_env().api == "graphql"


# ------------------------------------------------------- costo y tamaÃ±o de pÃ¡gina
def test_siguiente_tamano():
    assert siguiente_tamano(3, 300) == 9  # 100 puntos por pedido â†’ 900 / 100
    assert siguiente_tamano(10, 5000) == 1  # nunca menos de 1
    assert siguiente_tamano(1, 1) == 50  # tope MAX_PEDIDOS_POR_PAGINA
    assert siguiente_tamano(4, None) == 4  # sin dato de costo, se mantiene


@responses.activate
def test_pagina_se_ajusta_con_el_costo_reportado(gql_client, flt, respuesta):
    primera = copy.deepcopy(respuesta)
    primera["data"]["orders"]["pageInfo"] = {"hasNextPage": True, "endCursor": "C1"}
    primera["extensions"]["cost"]["requestedQueryCost"] = 300  # pedido con first=3 â†’ 100 c/u
    segunda = copy.deepcopy(respuesta)
    segunda["data"]["orders"]["nodes"][0] |= {"id": "gid://shopify/Order/2", "legacyResourceId": "2"}
    responses.post(URL, json=primera)
    responses.post(URL, json=segunda)

    stats = EstadisticasGraphQL()
    list(extract_orders_graphql(gql_client, flt, por_pagina=3, stats=stats))

    assert [_consulta(c.request)[1]["first"] for c in responses.calls] == [3, 9]
    assert stats.paginas == 2
    assert stats.costo_real == 80  # 40 + 40 (actualQueryCost del fixture)


def test_consulta_pide_conexiones_pequenas():
    """Los first: anidados multiplican el costo: se piden pocos y el resto se pagina."""
    assert f"lineItems(first: {LINEAS_POR_PAGINA})" in ORDERS_QUERY
    assert f"fulfillmentOrders(first: {BODEGAS_POR_PEDIDO})" in ORDERS_QUERY
    assert LINEAS_POR_PAGINA <= 5 and BODEGAS_POR_PEDIDO <= 2


@responses.activate
def test_bodegas_y_lineas_de_bodega_que_desbordan_se_paginan(gql_client, flt, respuesta):
    nodo = respuesta["data"]["orders"]["nodes"][0]
    nodo["fulfillmentOrders"]["pageInfo"] = {"hasNextPage": True, "endCursor": "FO1"}
    nodo["fulfillmentOrders"]["nodes"][0]["lineItems"]["pageInfo"] = {"hasNextPage": True, "endCursor": "FL1"}
    otro_grupo = copy.deepcopy(nodo["fulfillmentOrders"]["nodes"][0])
    otro_grupo |= {"id": "gid://shopify/FulfillmentOrder/77"}
    otro_grupo["lineItems"] = {
        "pageInfo": {"hasNextPage": False},
        "nodes": [{"totalQuantity": 2, "lineItem": {"id": "gid://shopify/LineItem/888"}}],
    }
    mas_bodegas = {"data": {"order": {"fulfillmentOrders": {"pageInfo": {"hasNextPage": False},
                                                            "nodes": [otro_grupo]}}}}  # fmt: skip
    mas_lineas_bodega = {"data": {"fulfillmentOrder": {"lineItems": {"pageInfo": {"hasNextPage": False},
        "nodes": [{"totalQuantity": 1, "lineItem": {"id": "gid://shopify/LineItem/999"}}]}}}}  # fmt: skip
    responses.post(URL, json=respuesta)
    responses.post(URL, json=mas_bodegas)
    responses.post(URL, json=mas_lineas_bodega)

    (pedido,) = extract_orders_graphql(gql_client, flt)

    grupos = pedido[FULFILLMENT_KEY]
    assert [g["id"] for g in grupos][1] == 77
    assert [li["line_item_id"] for li in grupos[0]["line_items"]] == [50783188156781, 999]
    consultas = [_consulta(c.request) for c in responses.calls[1:]]
    assert "MasBodegas" in consultas[0][0] and consultas[0][1]["after"] == "FO1"
    assert "MasLineasBodega" in consultas[1][0] and consultas[1][1]["after"] == "FL1"


# ------------------------------------------------------------ payload corrupto
@responses.activate
def test_pedido_con_payload_inesperado_se_descarta_y_la_corrida_sigue(
    gql_client, flt, respuesta, tmp_path, caplog
):
    roto = copy.deepcopy(respuesta["data"]["orders"]["nodes"][0])
    roto |= {"id": "gid://shopify/Order/2", "legacyResourceId": "2", "name": "#1007", "lineItems": "basura"}
    respuesta["data"]["orders"]["nodes"].append(roto)
    responses.post(URL, json=_conteo(2))
    responses.post(URL, json=respuesta)
    responses.post(URL, json=_conteo(2))  # segundo conteo: sigue en 2 â†’ no cuadra

    caplog.set_level("INFO", logger="shopify_pipeline")
    result = run_extraction(gql_client, flt, output_dir=tmp_path, run_id="RUN9")

    assert (result.written_count, result.rechazados) == (1, 1)
    assert not result.reconciled  # â†’ el watermark no avanza y se reintenta en la prÃ³xima corrida
    (rechazado,) = json.loads((tmp_path / "RUN9.rechazados.json").read_text(encoding="utf-8"))
    assert rechazado["pedido"] == "#1007" and rechazado["error"].startswith("AttributeError")
    manifiesto = json.loads((tmp_path / "RUN9.manifest.json").read_text(encoding="utf-8"))
    assert manifiesto["rechazados"] == 1
    assert "etapa=extract estado=ok ok=1 corruptas=1" in caplog.text
