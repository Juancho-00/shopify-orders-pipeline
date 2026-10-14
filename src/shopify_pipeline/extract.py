"""
Orquestación de la fase 1: extracción de pedidos de Shopify a la zona *raw*.

Cada corrida genera dos archivos con el mismo ``run_id``:

    data/raw/shopify/orders/<run_id>.jsonl          # un pedido por línea (+ sus bodegas)
    data/raw/shopify/orders/<run_id>.manifest.json  # metadatos de la corrida (ventana, conteos, versión)

El JSONL guarda el pedido tal cual lo entrega Shopify y, si se consultaron las bodegas,
la clave adicional ``_fulfillment_orders``. Con ese archivo se puede regenerar el
reporte para Siesa sin volver a llamar a la API (comando ``transform``).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from shopify_pipeline import __version__
from shopify_pipeline.shopify.client import ShopifyClient
from shopify_pipeline.shopify.fulfillment import BodegaEnricher
from shopify_pipeline.shopify.orders import OrderFilter, count_orders, extract_orders
from shopify_pipeline.sinks.jsonl import write_jsonl

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("data/raw/shopify/orders")


@dataclass(frozen=True)
class ExtractionResult:
    run_id: str
    shop_domain: str
    api_version: str
    status_filter: str
    date_field: str
    date_min: str
    date_max: str
    expected_count: int
    written_count: int
    bodegas_consultadas: int
    duration_seconds: float
    output_file: str
    pipeline_version: str = __version__

    @property
    def reconciled(self) -> bool:
        return self.expected_count == self.written_count


def new_run_id(now: datetime | None = None) -> str:
    """Identificador ordenable de la corrida, en UTC: ``20261013T161500Z``."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


def run_extraction(
    client: ShopifyClient,
    flt: OrderFilter,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_id: str | None = None,
    consultar_bodega: bool = True,
) -> ExtractionResult:
    """Extrae pedidos (y su bodega), los escribe en JSONL y genera el manifiesto."""
    run_id = run_id or new_run_id()
    output_file = output_dir / f"{run_id}.jsonl"
    cfg = client.config

    logger.info(
        "Extrayendo pedidos de %s (API %s) | status=%s | %s %s → %s",
        cfg.shop_domain,
        cfg.api_version,
        flt.status,
        flt.date_field,
        flt.date_min.isoformat(),
        flt.date_max.isoformat(),
    )
    expected = count_orders(client, flt)
    logger.info("Shopify reporta %d pedidos en la ventana.", expected)

    t0 = time.perf_counter()
    orders = extract_orders(client, flt)
    enricher = BodegaEnricher(client) if consultar_bodega else None
    if enricher:
        orders = enricher.enrich(orders)
    written = write_jsonl(orders, output_file)
    duration = round(time.perf_counter() - t0, 2)

    result = ExtractionResult(
        run_id=run_id,
        shop_domain=cfg.shop_domain,
        api_version=cfg.api_version,
        status_filter=flt.status,
        date_field=flt.date_field,
        date_min=flt.date_min.isoformat(),
        date_max=flt.date_max.isoformat(),
        expected_count=expected,
        written_count=written,
        bodegas_consultadas=enricher.enriched if enricher else 0,
        duration_seconds=duration,
        output_file=output_file.name,
    )
    _write_manifest(result, output_dir / f"{run_id}.manifest.json")

    logger.info("%d pedidos escritos en %s (%.1fs)", written, output_file, duration)
    if not result.reconciled:
        # Puede ocurrir si un pedido se elimina durante la corrida; si la diferencia es
        # grande, investigar antes de pasar a la conciliación con el ERP.
        logger.warning("Conciliación: Shopify reporta %d, se extrajeron %d.", expected, written)
    return result


def _write_manifest(result: ExtractionResult, path: Path) -> None:
    payload = asdict(result) | {"reconciled": result.reconciled}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
