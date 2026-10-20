"""Fixtures compartidas. Las pruebas no hacen llamadas reales: `responses` simula Shopify."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shopify_pipeline.config import ShopifyConfig
from shopify_pipeline.shopify.client import ShopifyClient
from shopify_pipeline.shopify.orders import OrderFilter

SHOP = "demo.myshopify.com"
API_VERSION = "2026-10"
BASE = f"https://{SHOP}/admin/api/{API_VERSION}"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Evita que variables reales del entorno del desarrollador afecten las pruebas."""
    for var in (
        "SHOPIFY_SHOP_DOMAIN",
        "SHOPIFY_API_VERSION",
        "SHOPIFY_ACCESS_TOKEN",
        "SHOPIFY_CLIENT_ID",
        "SHOPIFY_CLIENT_SECRET",
        "SIESA_CODIGO_ENVIO",
        "NOTIFICAR_A",
        "SMTP_USUARIO",
        "SMTP_CLAVE",
        "SMTP_HOST",
        "SMTP_PUERTO",
        "NOTIFICAR_SOLO_FALLOS",
        "SHOPIFY_API",
    ):
        monkeypatch.delenv(var, raising=False)
    # Las pruebas existentes simulan la API REST (el respaldo); las de GraphQL lo cambian.
    monkeypatch.setenv("SHOPIFY_API", "rest")


@pytest.fixture
def sleeps() -> list[float]:
    """Registra las pausas en lugar de dormir: las pruebas corren instantáneas."""
    return []


@pytest.fixture
def config() -> ShopifyConfig:
    return ShopifyConfig(shop_domain=SHOP, access_token="shpat_test", max_attempts=4, api="rest")


@pytest.fixture
def client(config, sleeps) -> ShopifyClient:
    return ShopifyClient(config, sleep=sleeps.append)


@pytest.fixture
def flt() -> OrderFilter:
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    return OrderFilter(date_min=now - timedelta(days=7), date_max=now)


@pytest.fixture
def orders_page() -> dict:
    return json.loads((FIXTURES / "orders_page.json").read_text(encoding="utf-8"))
