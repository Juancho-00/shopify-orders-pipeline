"""
Bodega de salida de cada producto (fulfillment orders).

El pedido de Shopify NO trae la bodega por línea. Esa información vive en las
*fulfillment orders*: Shopify divide cada pedido en uno o más grupos de productos y
asigna cada grupo a una ubicación (``assigned_location``). Se consulta con:

    GET /admin/api/{version}/orders/{order_id}/fulfillment_orders.json

Requiere el scope ``read_merchant_managed_fulfillment_orders`` (pedidos despachados por
la tienda). Es una llamada adicional por pedido; el cliente HTTP ya controla el rate limit.

El resultado se guarda dentro del pedido en la clave ``_fulfillment_orders`` (el guion
bajo indica que lo agregó el pipeline, no Shopify). Solo se guardan los campos necesarios.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from shopify_pipeline.exceptions import ShopifyNotFoundError, ShopifyPermissionError
from shopify_pipeline.shopify.client import ShopifyClient

logger = logging.getLogger(__name__)

FULFILLMENT_KEY = "_fulfillment_orders"


def _slim(fo: dict[str, Any]) -> dict[str, Any]:
    """Conserva solo lo necesario para resolver la bodega de cada línea."""
    location = fo.get("assigned_location") or {}
    return {
        "id": fo.get("id"),
        "status": fo.get("status"),
        "assigned_location_id": fo.get("assigned_location_id"),
        "assigned_location": {
            "location_id": location.get("location_id"),
            "name": location.get("name"),
        },
        "line_items": [
            {"line_item_id": li.get("line_item_id"), "quantity": li.get("quantity")}
            for li in fo.get("line_items") or []
        ],
    }


def fetch_fulfillment_orders(client: ShopifyClient, order_id: int) -> list[dict[str, Any]]:
    resp = client.get(f"orders/{order_id}/fulfillment_orders.json")
    return [_slim(fo) for fo in resp.json().get("fulfillment_orders", [])]


class BodegaEnricher:
    """
    Agrega ``_fulfillment_orders`` a cada pedido.

    Si el token no tiene el scope necesario (403), registra el error una sola vez,
    deja de consultar y continúa: los pedidos salen sin bodega y con la alerta
    ``SIN_BODEGA``, en lugar de detener toda la extracción.

    Si un pedido puntual responde 404 (p. ej. se eliminó durante la corrida), se registra
    y se sigue con el siguiente: un pedido no debe tumbar la extracción completa.

    ``debe_consultar`` (opcional) decide pedido por pedido si vale la pena gastar la
    llamada: la CLI la usa para saltarse los pedidos que no van a salir en el reporte
    (pendientes de pago, cancelados, de prueba o ya reportados). Sin ella, consulta todos.
    """

    def __init__(
        self,
        client: ShopifyClient,
        debe_consultar: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self.client = client
        self.debe_consultar = debe_consultar
        self.enabled = True
        self.enriched = 0
        self.omitidos = 0  # Pedidos a los que no se les consultó la bodega por no ser necesarios.

    def enrich(self, orders: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        for order in orders:
            if self.enabled and self.debe_consultar is not None and not self.debe_consultar(order):
                self.omitidos += 1
            elif self.enabled:
                try:
                    order[FULFILLMENT_KEY] = fetch_fulfillment_orders(self.client, order["id"])
                    self.enriched += 1
                except ShopifyPermissionError as exc:
                    logger.error(
                        "Sin permiso para consultar bodegas (%s). Agregue el scope "
                        "'read_merchant_managed_fulfillment_orders' a la app. "
                        "Se continúa sin bodega.",
                        exc,
                    )
                    self.enabled = False
                except ShopifyNotFoundError as exc:
                    logger.warning("Bodega no disponible para el pedido %s: %s", order.get("name"), exc)
            yield order


def location_by_line_item(fulfillment_orders: list[dict[str, Any]]) -> dict[int, tuple[Any, str]]:
    """
    Devuelve ``{line_item_id: (location_id, nombre_bodega)}``.

    Se ignoran las fulfillment orders canceladas y las líneas con cantidad 0 (quedan así
    cuando un grupo se mueve a otra bodega); si una línea aparece varias veces, gana la
    última asignación con cantidad.
    """
    result: dict[int, tuple[Any, str]] = {}
    for fo in fulfillment_orders:
        if fo.get("status") == "cancelled":
            continue
        location = fo.get("assigned_location") or {}
        location_id = location.get("location_id") or fo.get("assigned_location_id")
        name = location.get("name") or ""
        for li in fo.get("line_items") or []:
            line_id = li.get("line_item_id")
            if line_id is None:
                continue
            if (li.get("quantity") or 0) > 0 or line_id not in result:
                result[line_id] = (location_id, name)
    return result
