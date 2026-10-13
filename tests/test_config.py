import pytest

from shopify_pipeline.config import DEFAULT_API_VERSION, ShopifyConfig


def test_rechaza_dominio_publico():
    with pytest.raises(ValueError, match=r"myshopify\.com"):
        ShopifyConfig(shop_domain="www.mitienda.com", access_token="x")


def test_normaliza_dominio():
    cfg = ShopifyConfig(shop_domain=" https://Demo.myshopify.com/ ", access_token="x")
    assert cfg.shop_domain == "demo.myshopify.com"


def test_exige_credenciales():
    with pytest.raises(ValueError, match="credenciales"):
        ShopifyConfig(shop_domain="demo.myshopify.com")


def test_client_credentials_incompletas():
    with pytest.raises(ValueError):
        ShopifyConfig(shop_domain="demo.myshopify.com", client_id="solo-id")


def test_secretos_fuera_del_repr():
    cfg = ShopifyConfig(
        shop_domain="demo.myshopify.com",
        access_token="shpat_supersecreto",
        client_id="cid_secreto",
        client_secret="cs_secreto",
    )
    text = repr(cfg)
    assert "supersecreto" not in text
    assert "cid_secreto" not in text
    assert "cs_secreto" not in text


def test_from_env(monkeypatch):
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", "demo.myshopify.com")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "cs")
    cfg = ShopifyConfig.from_env()
    assert cfg.api_version == DEFAULT_API_VERSION
    assert cfg.access_token is None


def test_from_env_sin_dominio():
    with pytest.raises(ValueError, match="SHOPIFY_SHOP_DOMAIN"):
        ShopifyConfig.from_env()
