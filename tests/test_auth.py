import pytest
import responses

from shopify_pipeline.config import ShopifyConfig
from shopify_pipeline.exceptions import ShopifyAuthError
from shopify_pipeline.shopify.auth import (
    ClientCredentialsTokenProvider,
    StaticTokenProvider,
    build_token_provider,
)
from shopify_pipeline.shopify.client import ShopifyClient
from shopify_pipeline.shopify.orders import extract_orders
from tests.conftest import BASE, SHOP

TOKEN_URL = f"https://{SHOP}/admin/oauth/access_token"


def test_build_provider_elige_modo():
    static = build_token_provider(ShopifyConfig(shop_domain=SHOP, access_token="shpat_x"))
    cc = build_token_provider(ShopifyConfig(shop_domain=SHOP, client_id="a", client_secret="b"))
    assert isinstance(static, StaticTokenProvider)
    assert isinstance(cc, ClientCredentialsTokenProvider)


def test_repr_no_expone_secretos():
    assert "shpat_x" not in repr(StaticTokenProvider("shpat_x"))
    assert "secreto" not in repr(ClientCredentialsTokenProvider(SHOP, "id", "secreto"))


@responses.activate
def test_client_credentials_cachea_token():
    responses.post(TOKEN_URL, json={"access_token": "tok_1", "expires_in": 86399})
    provider = ClientCredentialsTokenProvider(SHOP, "cid", "secret")
    assert provider.get_token() == "tok_1"
    assert provider.get_token() == "tok_1"
    assert len(responses.calls) == 1
    body = responses.calls[0].request.body
    assert "grant_type=client_credentials" in body


@responses.activate
def test_client_credentials_renueva_si_va_a_expirar():
    responses.post(TOKEN_URL, json={"access_token": "tok_1", "expires_in": 100})
    responses.post(TOKEN_URL, json={"access_token": "tok_2", "expires_in": 100})
    provider = ClientCredentialsTokenProvider(SHOP, "cid", "secret", refresh_margin=300)
    assert provider.get_token() == "tok_1"
    assert provider.get_token() == "tok_2"  # expires_in < margen → renueva


@responses.activate
def test_client_credentials_error_no_filtra_secreto():
    responses.post(TOKEN_URL, status=400, body="client_secret=secreto invalid")
    provider = ClientCredentialsTokenProvider(SHOP, "cid", "secreto")
    with pytest.raises(ShopifyAuthError) as exc_info:
        provider.get_token()
    assert "secreto" not in str(exc_info.value)


@responses.activate
def test_renueva_token_ante_401(sleeps, flt):
    responses.post(TOKEN_URL, json={"access_token": "tok_1", "expires_in": 86399})
    responses.post(TOKEN_URL, json={"access_token": "tok_2", "expires_in": 86399})
    responses.get(f"{BASE}/orders.json", status=401)
    responses.get(f"{BASE}/orders.json", json={"orders": [{"id": 9}]})

    cfg = ShopifyConfig(shop_domain=SHOP, client_id="cid", client_secret="secret")
    client = ShopifyClient(cfg, sleep=sleeps.append)

    assert [o["id"] for o in extract_orders(client, flt)] == [9]
    assert responses.calls[1].request.headers["X-Shopify-Access-Token"] == "tok_1"
    assert responses.calls[3].request.headers["X-Shopify-Access-Token"] == "tok_2"


@responses.activate
def test_token_estatico_401_no_reintenta(client, flt):
    responses.get(f"{BASE}/orders.json", status=401)
    with pytest.raises(ShopifyAuthError):
        list(extract_orders(client, flt))
    assert len(responses.calls) == 1
