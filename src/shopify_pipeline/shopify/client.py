"""
Cliente HTTP para la REST Admin API de Shopify.

* Reintentos con ``tenacity``: 429 (respeta ``Retry-After``), 5xx, timeouts y errores de red.
* Throttling proactivo con la cabecera ``X-Shopify-Shop-Api-Call-Limit`` (leaky bucket).
* Paginación por cursor siguiendo la cabecera ``Link`` (rel="next").
* Errores no recuperables (401/403/404/4xx) tipados y sin reintento.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

import requests
from tenacity import (
    RetryCallState,
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from shopify_pipeline import __version__
from shopify_pipeline.config import ShopifyConfig
from shopify_pipeline.exceptions import (
    ShopifyAuthError,
    ShopifyClientError,
    ShopifyNotFoundError,
    ShopifyPermissionError,
    ShopifyRetryableError,
)
from shopify_pipeline.shopify.auth import TokenProvider, build_token_provider

logger = logging.getLogger(__name__)

USER_AGENT = f"shopify-pipeline/{__version__} (+data-engineering)"

RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ShopifyRetryableError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _wait_strategy(retry_state: RetryCallState) -> float:
    """Usa ``Retry-After`` si Shopify lo envía (429); si no, backoff exponencial con jitter."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, ShopifyRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_random_exponential(multiplier=1, max=60)(retry_state)


class ShopifyClient:
    """Cliente REST mínimo con reintentos, throttling y paginación."""

    def __init__(
        self,
        config: ShopifyConfig,
        token_provider: TokenProvider | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.token_provider = token_provider or build_token_provider(config)
        self.base_url = f"https://{config.shop_domain}/admin/api/{config.api_version}"
        self._sleep = sleep
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})
        self._retrying = Retrying(
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            wait=_wait_strategy,
            stop=stop_after_attempt(config.max_attempts),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            sleep=sleep,
            reraise=True,
        )

    # ------------------------------------------------------------- throttling
    def _throttle(self, response: requests.Response) -> None:
        """
        Leaky bucket proactivo. Cabecera: ``X-Shopify-Shop-Api-Call-Limit: 32/40``.

        Tasa de fuga ≈ capacidad/20 por segundo (40 → 2 req/s estándar; 400 → 20 req/s Plus).
        Si el bucket supera el umbral, espera hasta que drene a ~50 %.
        """
        header = response.headers.get("X-Shopify-Shop-Api-Call-Limit")
        if not header:
            return
        try:
            used, capacity = (int(x) for x in header.split("/"))
        except ValueError:
            return
        if capacity <= 0 or used / capacity < self.config.throttle_threshold:
            return
        leak_rate = max(capacity / 20.0, 1.0)
        pause = (used - capacity * 0.5) / leak_rate
        logger.debug("Bucket en %s; pausa proactiva de %.1fs", header, pause)
        self._sleep(pause)

    # --------------------------------------------------------------- requests
    def _send_once(self, url: str, params: dict[str, Any] | None) -> requests.Response:
        headers = {"X-Shopify-Access-Token": self.token_provider.get_token()}
        resp = self.session.get(url, params=params, headers=headers, timeout=self.config.timeout)
        status = resp.status_code

        if status == 200:
            self._throttle(resp)
            return resp

        request_id = resp.headers.get("X-Request-Id", "n/d")
        path = resp.request.path_url if resp.request is not None else url
        detail = f"HTTP {status} en {path} (X-Request-Id={request_id})"

        if status == 429:
            retry_after = float(resp.headers.get("Retry-After", 2.0))
            raise ShopifyRetryableError(f"Rate limit: {detail}", retry_after=retry_after)
        if status >= 500:
            raise ShopifyRetryableError(f"Error del servidor: {detail}")
        if status == 401:
            raise ShopifyAuthError(f"No autorizado: {detail}. Token inválido, revocado o expirado.")
        if status == 403:
            raise ShopifyPermissionError(
                f"Prohibido: {detail}. Verifique el scope 'read_orders' "
                "(y 'read_all_orders' para pedidos de más de 60 días)."
            )
        if status == 404:
            raise ShopifyNotFoundError(
                f"No encontrado: {detail}. Revise el dominio *.myshopify.com y la versión de API."
            )
        raise ShopifyClientError(f"{detail}: {resp.text[:500]}")

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("https://"):
            return path_or_url
        return f"{self.base_url}/{path_or_url.lstrip('/')}"

    def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> requests.Response:
        """GET con reintentos. Ante un 401 renueva el token una sola vez (si el modo lo permite)."""
        url = self._url(path_or_url)
        try:
            return self._retrying.copy()(self._send_once, url, params)
        except ShopifyAuthError:
            if self.token_provider.invalidate():
                logger.warning("401 recibido; renovando token y reintentando una vez.")
                return self._retrying.copy()(self._send_once, url, params)
            raise

    def paginate(self, path: str, params: dict[str, Any]) -> Iterator[requests.Response]:
        """
        Recorre todas las páginas siguiendo ``Link: <...page_info=...>; rel="next"``.

        La URL "next" ya trae ``page_info`` y ``limit``. Shopify rechaza otros filtros
        junto a ``page_info``, por eso NO se reenvían los params originales: los filtros
        quedan "congelados" dentro del cursor.
        """
        url: str | None = path
        current_params: dict[str, Any] | None = params
        page = 0
        while url:
            resp = self.get(url, current_params)
            page += 1
            logger.debug("Página %d descargada", page)
            yield resp
            url = resp.links.get("next", {}).get("url")
            current_params = None
