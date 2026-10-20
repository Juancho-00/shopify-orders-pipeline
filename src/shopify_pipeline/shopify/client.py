"""
Cliente HTTP para la Admin API de Shopify: GraphQL (la que se usa) y REST (respaldo).

QUÉ HACE
    Es el único archivo que "habla" con Shopify. Todos los demás le piden datos a él.

RESPONSABILIDADES
    1. Armar la URL y poner el token en cada petición.
    2. Revisar la respuesta y convertir los errores HTTP en errores con nombre propio
       (ver ``exceptions.py``).
    3. Reintentar cuando el error es temporal (429, 5xx, caída de red).
    4. Frenar a tiempo para no superar el límite de llamadas de Shopify.
    5. Recorrer todas las páginas de un listado (REST).
    6. Enviar consultas GraphQL (``graphql``) y traducir sus errores.

EL LÍMITE DE LLAMADAS (leaky bucket o "balde con fuga")
    Shopify le da a cada tienda un balde de 40 llamadas (400 en Shopify Plus). Cada
    llamada echa una gota y el balde se vacía solo a 2 gotas por segundo (20 en Plus).
    Si el balde se llena, Shopify responde 429 ("demasiadas peticiones").
    Cada respuesta trae la cabecera ``X-Shopify-Shop-Api-Call-Limit: 36/40`` que dice
    cuán lleno está. Si pasa del 80 %, esperamos a que baje al 50 % antes de seguir.

    En GraphQL el balde se mide en *puntos de costo* (cada campo pedido cuesta puntos) y la
    respuesta trae el estado en ``extensions.cost.throttleStatus``: puntos disponibles,
    máximo y cuántos se recuperan por segundo. Se frena igual: si queda menos del 20 %,
    se espera a recuperar la mitad. Si Shopify responde ``THROTTLED``, se reintenta.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator
from typing import Any

import requests

from shopify_pipeline import __version__
from shopify_pipeline.config import ShopifyConfig
from shopify_pipeline.exceptions import (
    ShopifyAuthError,
    ShopifyClientError,
    ShopifyCostoExcedidoError,
    ShopifyNotFoundError,
    ShopifyPermissionError,
    ShopifyRetryableError,
)
from shopify_pipeline.shopify.auth import TokenProvider, build_token_provider

logger = logging.getLogger(__name__)

USER_AGENT = f"shopify-pipeline/{__version__} (+data-engineering)"

# Errores temporales: vale la pena esperar y volver a intentar.
ERRORES_TEMPORALES: tuple[type[Exception], ...] = (
    ShopifyRetryableError,  # 429 o 5xx
    requests.exceptions.ConnectionError,  # sin conexión, DNS
    requests.exceptions.Timeout,  # Shopify tardó demasiado
    requests.exceptions.ChunkedEncodingError,  # respuesta cortada a la mitad
)

ESPERA_MAXIMA = 60.0  # segundos


def segundos_de_espera(intento: int, error: Exception) -> float:
    """
    Cuánto esperar antes del siguiente intento.

    * Si Shopify dijo cuánto esperar (cabecera ``Retry-After`` en un 429), se respeta.
    * Si no, *backoff exponencial con jitter*: 1 s, 2 s, 4 s, 8 s... (máximo 60 s),
      con un componente aleatorio para que varios procesos no reintenten al mismo tiempo.
    """
    if isinstance(error, ShopifyRetryableError) and error.retry_after is not None:
        return error.retry_after
    return random.uniform(0, min(2.0**intento, ESPERA_MAXIMA))


class ShopifyClient:
    """Cliente REST mínimo con reintentos, control de límite y paginación."""

    def __init__(
        self,
        config: ShopifyConfig,
        token_provider: TokenProvider | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """
        ``token_provider``, ``session`` y ``sleep`` son opcionales: en producción se usan
        los valores por defecto; las pruebas pasan versiones falsas (por ejemplo, un
        ``sleep`` que no duerme) para correr en milisegundos.
        """
        self.config = config
        # ``extensions.cost`` de la última consulta GraphQL exitosa (requestedQueryCost,
        # actualQueryCost, throttleStatus). La extracción lo usa para ajustar el tamaño de
        # página y para registrar el costo de cada lote.
        self.ultimo_costo: dict[str, Any] = {}
        self.token_provider = token_provider or build_token_provider(config)
        self.base_url = f"https://{config.shop_domain}/admin/api/{config.api_version}"
        self._sleep = sleep
        # Una sesión reutiliza la conexión entre llamadas: más rápido que abrir una por petición.
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})

    # ---------------------------------------------------------- límite de llamadas
    def _frenar_si_el_balde_esta_lleno(self, response: requests.Response) -> None:
        header = response.headers.get("X-Shopify-Shop-Api-Call-Limit")  # p. ej. "36/40"
        if not header:
            return
        try:
            usadas, capacidad = (int(x) for x in header.split("/"))
        except ValueError:
            return
        if capacidad <= 0 or usadas / capacidad < self.config.throttle_threshold:
            return
        vaciado_por_segundo = max(capacidad / 20.0, 1.0)  # 40 → 2/s; 400 → 20/s
        pausa = (usadas - capacidad * 0.5) / vaciado_por_segundo
        logger.debug("Balde en %s; pausa preventiva de %.1fs", header, pausa)
        self._sleep(pausa)

    # ----------------------------------------------------------- una sola petición
    def _pedir_una_vez(
        self, url: str, params: dict[str, Any] | None, json: dict[str, Any] | None = None
    ) -> requests.Response:
        """Hace UNA petición y traduce el código HTTP a éxito o a un error con nombre."""
        headers = {"X-Shopify-Access-Token": self.token_provider.get_token()}
        if json is None:
            resp = self.session.get(url, params=params, headers=headers, timeout=self.config.timeout)
        else:
            resp = self.session.post(url, json=json, headers=headers, timeout=self.config.timeout)
        status = resp.status_code

        if status == 200:
            self._frenar_si_el_balde_esta_lleno(resp)
            return resp

        # X-Request-Id identifica la petición si hay que escribirle a soporte de Shopify.
        request_id = resp.headers.get("X-Request-Id", "n/d")
        path = resp.request.path_url if resp.request is not None else url
        detalle = f"HTTP {status} en {path} (X-Request-Id={request_id})"

        if status == 429:
            retry_after = float(resp.headers.get("Retry-After", 2.0))
            raise ShopifyRetryableError(f"Límite de llamadas: {detalle}", retry_after=retry_after)
        if status >= 500:
            raise ShopifyRetryableError(f"Error del servidor: {detalle}")
        if status == 401:
            raise ShopifyAuthError(f"No autorizado: {detalle}. Token inválido, revocado o expirado.")
        if status == 403:
            raise ShopifyPermissionError(
                f"Prohibido: {detalle}. Verifique el scope 'read_orders' "
                "(y 'read_all_orders' para pedidos de más de 60 días)."
            )
        if status == 404:
            raise ShopifyNotFoundError(
                f"No encontrado: {detalle}. Revise el dominio *.myshopify.com y la versión de API."
            )
        raise ShopifyClientError(f"{detalle}: {resp.text[:500]}")

    # ------------------------------------------------------------ con reintentos
    def _pedir_con_reintentos(
        self, url: str, params: dict[str, Any] | None, json: dict[str, Any] | None = None
    ) -> requests.Response:
        """
        Llama a ``_pedir_una_vez`` hasta ``max_attempts`` veces si el error es temporal.
        Los errores definitivos (401, 403, 404...) salen de inmediato: reintentarlos no
        los arregla y solo gasta llamadas.
        """
        intentos = self.config.max_attempts
        for intento in range(1, intentos + 1):
            try:
                if json is None:
                    return self._pedir_una_vez(url, params)
                return self._graphql_una_vez(url, json)
            except ERRORES_TEMPORALES as error:
                if intento == intentos:
                    raise  # Se acabaron los intentos: el error sube a quien llamó.
                espera = segundos_de_espera(intento, error)
                logger.warning(
                    "Intento %d de %d falló (%s). Reintentando en %.1fs.", intento, intentos, error, espera
                )
                self._sleep(espera)
        raise AssertionError("inalcanzable")  # pragma: no cover

    def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> requests.Response:
        """
        Punto de entrada para pedir algo a Shopify.

        Acepta una ruta relativa (``"orders.json"``) o una URL completa (la de la página
        siguiente). Si Shopify responde 401 y el token se puede renovar (modo Client
        Credentials), pide un token nuevo y reintenta una sola vez.
        """
        url = (
            path_or_url
            if path_or_url.startswith("https://")
            else f"{self.base_url}/{path_or_url.lstrip('/')}"
        )
        try:
            return self._pedir_con_reintentos(url, params)
        except ShopifyAuthError:
            if not self.token_provider.invalidate():
                raise
            logger.warning("401 recibido; renovando token y reintentando una vez.")
            return self._pedir_con_reintentos(url, params)

    # ------------------------------------------------------------------ GraphQL
    def _graphql_una_vez(self, url: str, payload: dict[str, Any]) -> requests.Response:
        """
        Una consulta GraphQL. Shopify responde 200 aunque la consulta falle: los errores
        vienen en ``errors`` y aquí se traducen a los mismos errores con nombre de REST.
        """
        resp = self._pedir_una_vez(url, None, json=payload)
        cuerpo = resp.json()
        errores = cuerpo.get("errors") or []
        if errores:
            codigos = {(e.get("extensions") or {}).get("code", "") for e in errores}
            texto = "; ".join(str(e.get("message", "")) for e in errores)[:500]
            if "THROTTLED" in codigos:
                raise ShopifyRetryableError(
                    f"GraphQL: límite de costo alcanzado ({texto})", retry_after=self._espera_costo(cuerpo)
                )
            if "ACCESS_DENIED" in codigos:
                raise ShopifyPermissionError(
                    f"GraphQL: acceso denegado ({texto}). Revise los scopes de la app: read_orders, "
                    "read_all_orders, read_merchant_managed_fulfillment_orders y read_locations."
                )
            if "MAX_COST_EXCEEDED" in codigos:
                raise ShopifyCostoExcedidoError(f"GraphQL: la consulta cuesta demasiado ({texto})")
            if "INTERNAL_SERVER_ERROR" in codigos:
                raise ShopifyRetryableError(f"GraphQL: error interno de Shopify ({texto})")
            raise ShopifyClientError(f"GraphQL: {texto}")
        self.ultimo_costo = (cuerpo.get("extensions") or {}).get("cost") or {}
        self._frenar_por_costo(cuerpo)
        return resp

    @staticmethod
    def _throttle(cuerpo: dict[str, Any]) -> dict[str, Any]:
        return ((cuerpo.get("extensions") or {}).get("cost") or {}).get("throttleStatus") or {}

    def _espera_costo(self, cuerpo: dict[str, Any]) -> float:
        """Segundos hasta recuperar los puntos que pidió la consulta (THROTTLED)."""
        estado = self._throttle(cuerpo)
        costo = ((cuerpo.get("extensions") or {}).get("cost") or {}).get("requestedQueryCost") or 0
        disponible = float(estado.get("currentlyAvailable") or 0)
        recupera = float(estado.get("restoreRate") or 50)
        return min(max((costo - disponible) / recupera, 1.0), ESPERA_MAXIMA)

    def _frenar_por_costo(self, cuerpo: dict[str, Any]) -> None:
        estado = self._throttle(cuerpo)
        try:
            maximo = float(estado["maximumAvailable"])
            disponible = float(estado["currentlyAvailable"])
            recupera = float(estado["restoreRate"]) or 50.0
        except (KeyError, TypeError, ValueError):
            return
        if maximo <= 0 or disponible / maximo > 1 - self.config.throttle_threshold:
            return
        pausa = (maximo * 0.5 - disponible) / recupera
        logger.debug("Costo GraphQL: %s/%s disponibles; pausa preventiva de %.1fs", disponible, maximo, pausa)
        self._sleep(pausa)

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Ejecuta una consulta GraphQL y devuelve ``data``. Mismos reintentos y renovación de
        token que ``get``.
        """
        url = f"{self.base_url}/graphql.json"
        payload = {"query": query, "variables": variables or {}}
        try:
            resp = self._pedir_con_reintentos(url, None, json=payload)
        except ShopifyAuthError:
            if not self.token_provider.invalidate():
                raise
            logger.warning("401 recibido; renovando token y reintentando una vez.")
            resp = self._pedir_con_reintentos(url, None, json=payload)
        return resp.json().get("data") or {}

    # ------------------------------------------------------------------ páginas
    def paginate(self, path: str, params: dict[str, Any]) -> Iterator[requests.Response]:
        """
        Recorre todas las páginas de un listado, una por una.

        Shopify entrega máximo 250 pedidos por página. Al final de cada respuesta agrega
        la cabecera ``Link`` con la URL de la página siguiente (``rel="next"``). Cuando
        ya no hay ``next``, se terminó.

        Ojo: la URL "next" ya trae los filtros codificados en ``page_info``. Si se
        vuelven a enviar los filtros, Shopify responde error; por eso desde la segunda
        página ``params`` va vacío.

        ``yield`` entrega una página a la vez (no las acumula todas en memoria).
        """
        url: str | None = path
        params_actuales: dict[str, Any] | None = params
        pagina = 0
        while url:
            resp = self.get(url, params_actuales)
            pagina += 1
            logger.debug("Página %d descargada", pagina)
            yield resp
            url = resp.links.get("next", {}).get("url")  # requests ya interpreta la cabecera Link
            params_actuales = None
