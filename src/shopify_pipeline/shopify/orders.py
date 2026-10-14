"""Extracción de pedidos (orders) desde Shopify."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from shopify_pipeline.shopify.client import ShopifyClient

MAX_PAGE_SIZE = 250  # Máximo permitido por Shopify en endpoints REST de listado.
VALID_STATUSES = frozenset({"open", "closed", "cancelled", "any"})
# Campo de fecha por el que se filtra la ventana. Ambos los soportan orders.json y orders/count.json.
VALID_DATE_FIELDS = frozenset({"created_at", "updated_at"})


@dataclass(frozen=True)
class OrderFilter:
    """
    Filtros de la consulta.

    Se usa una ventana cerrada [date_min, date_max] fijada al inicio de la corrida: los
    pedidos que entren durante la extracción no alteran el resultado y la corrida es
    reproducible.

    ``date_field`` define sobre qué fecha se aplica la ventana:

    * ``created_at`` (default): pedidos *creados* en la ventana.
    * ``updated_at``: pedidos *modificados* en la ventana. Sirve para capturar pedidos
      creados antes cuyo pago se confirmó después (p. ej. contraentrega), porque marcar
      el pago actualiza el pedido.
    """

    date_min: datetime
    date_max: datetime
    status: str = "any"  # Shopify usa "open" por defecto: con "any" no se pierden cerrados/cancelados.
    fields: tuple[str, ...] | None = None  # Proyección de campos: reduce payload y latencia.
    page_size: int = MAX_PAGE_SIZE
    date_field: str = "created_at"

    def __post_init__(self) -> None:
        if self.date_min.tzinfo is None or self.date_max.tzinfo is None:
            raise ValueError("Use datetimes con zona horaria (timezone-aware).")
        if self.date_min >= self.date_max:
            raise ValueError("La fecha inicial debe ser anterior a la fecha final.")
        if self.date_field not in VALID_DATE_FIELDS:
            raise ValueError(f"date_field inválido: {self.date_field}. Opciones: {sorted(VALID_DATE_FIELDS)}")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"status inválido: {self.status}. Opciones: {sorted(VALID_STATUSES)}")
        if not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size debe estar entre 1 y {MAX_PAGE_SIZE}.")
        if self.fields is not None and "id" not in self.fields:
            # 'id' es necesario para deduplicar y conciliar.
            object.__setattr__(self, "fields", ("id", *self.fields))

    @classmethod
    def last_n_days(cls, days: int, **kwargs: Any) -> OrderFilter:
        if days <= 0:
            raise ValueError("days debe ser mayor que 0.")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return cls(date_min=now - timedelta(days=days), date_max=now, **kwargs)

    def filter_params(self) -> dict[str, Any]:
        """Filtros comunes a ``orders.json`` y ``orders/count.json``."""
        return {
            "status": self.status,
            f"{self.date_field}_min": self.date_min.isoformat(),
            f"{self.date_field}_max": self.date_max.isoformat(),
        }

    def list_params(self) -> dict[str, Any]:
        params = self.filter_params() | {"limit": self.page_size}
        if self.fields:
            params["fields"] = ",".join(self.fields)
        return params


def count_orders(client: ShopifyClient, flt: OrderFilter) -> int:
    """Cantidad esperada según Shopify, para conciliar al final de la corrida."""
    return int(client.get("orders/count.json", flt.filter_params()).json()["count"])


def extract_orders(client: ShopifyClient, flt: OrderFilter) -> Iterator[dict[str, Any]]:
    """Generador de pedidos (memoria constante). Deduplica por ``id`` como salvaguarda."""
    seen: set[int] = set()
    for resp in client.paginate("orders.json", flt.list_params()):
        for order in resp.json().get("orders", []):
            oid = order["id"]
            if oid in seen:
                continue
            seen.add(oid)
            yield order
