"""
Autenticación: de dónde sale el token que se envía en cada petición a Shopify.

QUÉ HACE
    Entrega el "pase de entrada" (access token) que el cliente HTTP pone en la cabecera
    ``X-Shopify-Access-Token``. Hay dos formas de conseguirlo:

    * ``StaticTokenProvider``: la app es *legacy* (creada en el admin antes de 2026) y
      tiene un token permanente ``shpat_...``. Solo lo devuelve tal cual.
    * ``ClientCredentialsTokenProvider``: la app se creó en el Dev Dashboard. Con
      ``client_id`` + ``client_secret`` se pide un token a Shopify; ese token vence en
      ~24 h, así que esta clase lo guarda y pide uno nuevo antes de que venza.

POR QUÉ DOS CLASES CON LOS MISMOS MÉTODOS
    El cliente HTTP no sabe (ni le importa) cuál de las dos está usando: solo llama
    ``get_token()`` e ``invalidate()``. Así se puede cambiar el modo de autenticación
    desde el ``.env`` sin tocar el resto del código.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

import requests

from shopify_pipeline.config import ShopifyConfig
from shopify_pipeline.exceptions import ShopifyAuthError

logger = logging.getLogger(__name__)


class TokenProvider(Protocol):
    """Contrato: cualquier clase con estos dos métodos sirve como proveedor de token."""

    def get_token(self) -> str: ...

    def invalidate(self) -> bool:
        """Descarta el token actual. Devuelve True si es posible obtener uno nuevo."""
        ...


class StaticTokenProvider:
    """Token permanente de una custom app legacy. No se puede renovar."""

    def __init__(self, token: str) -> None:
        self._token = token

    def get_token(self) -> str:
        return self._token

    def invalidate(self) -> bool:
        return False

    def __repr__(self) -> str:  # Nunca exponer el token.
        return "StaticTokenProvider(token=***)"


class ClientCredentialsTokenProvider:
    """
    Client Credentials Grant.

    Renueva el token ``refresh_margin`` segundos (5 min) antes de que venza, o cuando
    el cliente lo invalida tras recibir un 401.
    """

    def __init__(
        self,
        shop_domain: str,
        client_id: str,
        client_secret: str,
        timeout: tuple[float, float] = (10.0, 30.0),
        refresh_margin: float = 300.0,
        session: requests.Session | None = None,
    ) -> None:
        self._url = f"https://{shop_domain}/admin/oauth/access_token"
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout
        self._margin = refresh_margin
        self._session = session or requests.Session()
        self._token: str | None = None
        self._expires_at = 0.0  # Momento (reloj interno) en que vence el token actual.

    def get_token(self) -> str:
        vencido = self._token is None or time.monotonic() >= self._expires_at - self._margin
        if vencido:
            self._fetch()
        assert self._token is not None
        return self._token

    def invalidate(self) -> bool:
        self._token = None  # La próxima llamada a get_token() pedirá uno nuevo.
        return True

    def _fetch(self) -> None:
        logger.info("Solicitando access token (client credentials)...")
        try:
            resp = self._session.post(
                self._url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise ShopifyAuthError(f"No se pudo contactar el endpoint de OAuth: {exc}") from exc

        if resp.status_code != 200:
            # No se registra el cuerpo: podría reflejar los parámetros enviados.
            raise ShopifyAuthError(
                f"Fallo al obtener token (HTTP {resp.status_code}). Verifique client_id/secret, "
                "que la app esté instalada en la tienda y que la versión con scopes esté publicada."
            )
        payload = resp.json()
        self._token = payload["access_token"]
        self._expires_at = time.monotonic() + float(payload.get("expires_in", 86_399))
        logger.info("Token obtenido. Scopes: %s", payload.get("scope", "n/d"))

    def __repr__(self) -> str:
        return "ClientCredentialsTokenProvider(client_secret=***)"


def build_token_provider(config: ShopifyConfig) -> TokenProvider:
    """Elige el modo de autenticación según las credenciales disponibles."""
    if config.access_token:
        return StaticTokenProvider(config.access_token)
    assert config.client_id and config.client_secret
    return ClientCredentialsTokenProvider(
        config.shop_domain, config.client_id, config.client_secret, timeout=config.timeout
    )
