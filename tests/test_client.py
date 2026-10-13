import pytest
import requests
import responses

from shopify_pipeline.exceptions import (
    ShopifyClientError,
    ShopifyNotFoundError,
    ShopifyPermissionError,
    ShopifyRetryableError,
)
from tests.conftest import BASE

ORDERS_URL = f"{BASE}/orders.json"


@responses.activate
def test_envia_token_y_user_agent(client):
    responses.get(ORDERS_URL, json={"orders": []})
    client.get("orders.json")
    headers = responses.calls[0].request.headers
    assert headers["X-Shopify-Access-Token"] == "shpat_test"
    assert headers["User-Agent"].startswith("shopify-pipeline/")


@responses.activate
def test_paginacion_sigue_link_sin_reenviar_filtros(client):
    next_url = f"{ORDERS_URL}?limit=250&page_info=abc123"
    last_url = f"{ORDERS_URL}?limit=250&page_info=def456"
    responses.get(ORDERS_URL, json={"page": 1}, headers={"Link": f'<{next_url}>; rel="next"'})
    responses.get(
        next_url,
        json={"page": 2},
        headers={"Link": f'<{ORDERS_URL}?page_info=prev>; rel="previous", <{last_url}>; rel="next"'},
    )
    responses.get(last_url, json={"page": 3})

    pages = [r.json()["page"] for r in client.paginate("orders.json", {"status": "any", "limit": 250})]
    assert pages == [1, 2, 3]
    assert "status=any" in responses.calls[0].request.url
    for call in responses.calls[1:]:
        assert "status" not in call.request.url


@responses.activate
def test_429_respeta_retry_after(client, sleeps):
    responses.get(ORDERS_URL, status=429, headers={"Retry-After": "2.0"})
    responses.get(ORDERS_URL, json={"orders": []})
    client.get("orders.json")
    assert sleeps == [2.0]


@responses.activate
def test_429_sin_retry_after_usa_default(client, sleeps):
    responses.get(ORDERS_URL, status=429)
    responses.get(ORDERS_URL, json={"orders": []})
    client.get("orders.json")
    assert sleeps == [2.0]


@responses.activate
def test_5xx_reintenta_y_agota(client):
    responses.get(ORDERS_URL, status=503)
    with pytest.raises(ShopifyRetryableError):
        client.get("orders.json")
    assert len(responses.calls) == 4  # max_attempts del fixture


@responses.activate
def test_5xx_se_recupera(client, sleeps):
    responses.get(ORDERS_URL, status=502)
    responses.get(ORDERS_URL, status=500)
    responses.get(ORDERS_URL, json={"orders": []})
    assert client.get("orders.json").status_code == 200
    assert len(sleeps) == 2


@responses.activate
def test_error_de_red_reintenta(client):
    responses.get(ORDERS_URL, body=requests.exceptions.ConnectionError("caída"))
    responses.get(ORDERS_URL, json={"orders": []})
    assert client.get("orders.json").status_code == 200


@pytest.mark.parametrize(
    ("status", "exc", "match"),
    [
        (403, ShopifyPermissionError, "read_orders"),
        (404, ShopifyNotFoundError, r"myshopify\.com"),
        (422, ShopifyClientError, "422"),
    ],
)
@responses.activate
def test_4xx_no_reintenta(client, status, exc, match):
    responses.get(ORDERS_URL, status=status)
    with pytest.raises(exc, match=match):
        client.get("orders.json")
    assert len(responses.calls) == 1


@responses.activate
def test_throttle_proactivo(client, sleeps):
    responses.get(ORDERS_URL, json={}, headers={"X-Shopify-Shop-Api-Call-Limit": "36/40"})
    client.get("orders.json")
    assert sleeps == [8.0]  # (36 - 20) / 2 req/s


@responses.activate
def test_throttle_no_pausa_bajo_umbral(client, sleeps):
    responses.get(ORDERS_URL, json={}, headers={"X-Shopify-Shop-Api-Call-Limit": "10/40"})
    client.get("orders.json")
    assert sleeps == []


@responses.activate
def test_throttle_tienda_plus(client, sleeps):
    responses.get(ORDERS_URL, json={}, headers={"X-Shopify-Shop-Api-Call-Limit": "380/400"})
    client.get("orders.json")
    assert sleeps == [9.0]  # (380 - 200) / 20 req/s
