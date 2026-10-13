"""Extracción de pedidos (orders) desde Shopify."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from shopify_pipeline.shopify.client import ShopifyClient

MAX_PAGE_SIZE = 250  # Máximo permitido por Shopify en endpoints REST de listado.
VALID_STATUSES = frozenset({"open", "closed", "cancelled", "any"})


@dataclass(frozen=True)
class OrderFilter:
    """
    Filtros de la consulta.

    Se usa una ventana cerrada [created_at_min, created_at_max] fijada al inicio de la
    corrida: los pedidos que entren durante la extracción no alteran el resultado y la
    corrida es reproducible.
    """

    created_at_min: datetime
    created_at_max: datetime
    status: str = "any"  # Shopify usa "open" por defecto: con "any" no se pierden cerrados/cancelados.
    fields: tuple[str, ...] | None = None  # Proyección de campos: reduce payload y latencia.
    page_size: int = MAX_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.created_at_min.tzinfo is None or self.created_at_max.tzinfo is None:
            raise ValueError("Use datetimes con zona horaria (timezone-aware).")
        if self.created_at_min >= self.created_at_max:
            raise ValueError("created_at_min debe ser anterior a created_at_max.")
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
        return cls(created_at_min=now - timedelta(days=days), created_at_max=now, **kwargs)

    def filter_params(self) -> dict[str, Any]:
        """Filtros comunes a ``orders.json`` y ``orders/count.json``."""
        return {
            "status": self.status,
            "created_at_min": self.created_at_min.isoformat(),
            "created_at_max": self.created_at_max.isoformat(),
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
