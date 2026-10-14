from datetime import datetime, timedelta, timezone

import pytest
import responses

from shopify_pipeline.shopify.orders import OrderFilter, count_orders, extract_orders
from tests.conftest import BASE

ORDERS_URL = f"{BASE}/orders.json"


def test_filter_params(flt):
    params = flt.list_params()
    assert params["status"] == "any"
    assert params["limit"] == 250
    assert params["created_at_min"] == "2026-10-06T00:00:00+00:00"
    assert params["created_at_max"] == "2026-10-13T00:00:00+00:00"
    assert "fields" not in params


def test_filtro_por_fecha_de_actualizacion(flt):
    f = OrderFilter(flt.date_min, flt.date_max, date_field="updated_at")
    params = f.filter_params()
    assert params["updated_at_min"] == "2026-10-06T00:00:00+00:00"
    assert "created_at_min" not in params


def test_date_field_invalido(flt):
    with pytest.raises(ValueError, match="date_field"):
        OrderFilter(flt.date_min, flt.date_max, date_field="processed_at")


def test_fields_siempre_incluye_id(flt):
    f = OrderFilter(flt.date_min, flt.date_max, fields=("name", "total_price"))
    assert f.list_params()["fields"] == "id,name,total_price"


def test_last_n_days():
    f = OrderFilter.last_n_days(7)
    assert f.date_max - f.date_min == timedelta(days=7)
    assert f.date_max.tzinfo is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "abierto"},
        {"page_size": 251},
        {"page_size": 0},
    ],
)
def test_validaciones(flt, kwargs):
    with pytest.raises(ValueError):
        OrderFilter(flt.date_min, flt.date_max, **kwargs)


def test_rechaza_fechas_sin_zona_horaria():
    with pytest.raises(ValueError, match="zona horaria"):
        OrderFilter(datetime(2026, 10, 1), datetime(2026, 10, 2))


def test_rechaza_ventana_invertida():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        OrderFilter(now, now - timedelta(days=1))


@responses.activate
def test_extract_pagina_y_deduplica(client, flt):
    next_url = f"{ORDERS_URL}?limit=250&page_info=abc123"
    responses.get(
        ORDERS_URL,
        json={"orders": [{"id": 1}, {"id": 2}]},
        headers={"Link": f'<{next_url}>; rel="next"'},
        match=[responses.matchers.query_param_matcher(flt.list_params())],
    )
    responses.get(next_url, json={"orders": [{"id": 3}, {"id": 2}]})  # id 2 duplicado

    assert [o["id"] for o in extract_orders(client, flt)] == [1, 2, 3]


@responses.activate
def test_extract_con_fixture_real(client, flt, orders_page):
    responses.get(ORDERS_URL, json=orders_page)
    orders = list(extract_orders(client, flt))
    assert [o["name"] for o in orders] == ["#1001", "#1002"]
    assert orders[0]["line_items"][0]["sku"] == "SKU-0001"


@responses.activate
def test_count_orders(client, flt):
    responses.get(
        f"{BASE}/orders/count.json",
        json={"count": 42},
        match=[responses.matchers.query_param_matcher(flt.filter_params())],
    )
    assert count_orders(client, flt) == 42
