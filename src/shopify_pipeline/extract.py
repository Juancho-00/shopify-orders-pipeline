"""
Orquestación de la fase 1: extracción de pedidos de Shopify a la zona *raw*.

Cada corrida genera dos archivos con el mismo ``run_id``:

    data/raw/shopify/orders/<run_id>.jsonl          # un pedido por línea (+ sus bodegas)
    data/raw/shopify/orders/<run_id>.manifest.json  # metadatos de la corrida (ventana, conteos, versión)

El manifiesto es el contrato con las etapas siguientes: ``transform`` lo lee para saber si
la extracción cuadró y si se hizo con ``--fields`` (proyección de campos).

El JSONL guarda el pedido tal cual lo entrega Shopify y, si se consultaron las bodegas,
la clave adicional ``_fulfillment_orders``. Con ese archivo se puede regenerar el
reporte para Siesa sin volver a llamar a la API (comando ``transform``).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shopify_pipeline import __version__
from shopify_pipeline.exceptions import ConfigError
from shopify_pipeline.shopify.client import ShopifyClient
from shopify_pipeline.shopify.fulfillment import BodegaEnricher
from shopify_pipeline.shopify.graphql_orders import count_orders_graphql, extract_orders_graphql
from shopify_pipeline.shopify.orders import OrderFilter, count_orders, extract_orders
from shopify_pipeline.sinks.atomic import write_json_atomic
from shopify_pipeline.sinks.jsonl import write_jsonl

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("data/raw/shopify/orders")
# Versión del formato del manifiesto. Subirla si se cambia el significado de un campo.
MANIFEST_SCHEMA_VERSION = 2


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
    fields: list[str] | None = None  # None = pedido completo; lista = proyección con --fields
    incremental: bool = False
    bodegas_omitidas: int = 0  # Pedidos sin consulta de bodega por no ir al reporte
    api: str = "rest"  # API con la que se extrajo: "graphql" o "rest"
    # Segundo conteo, solo si el primero no cuadró (ver ``run_extraction``). None = no hizo falta.
    recount_count: int | None = None
    pipeline_version: str = __version__
    schema_version: int = MANIFEST_SCHEMA_VERSION

    @property
    def reconciled(self) -> bool:
        objetivo = self.expected_count if self.recount_count is None else self.recount_count
        return objetivo == self.written_count


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
    incremental: bool = False,
    debe_consultar_bodega: Callable[[dict[str, Any]], bool] | None = None,
) -> ExtractionResult:
    """Extrae pedidos (y su bodega), los escribe en JSONL y genera el manifiesto."""
    run_id = run_id or new_run_id()
    output_file = output_dir / f"{run_id}.jsonl"
    if output_file.exists():
        # La zona raw es inmutable: una extracción nunca reemplaza a otra.
        raise ConfigError(f"Ya existe la extracción {output_file.name}; espere un segundo y reintente.")
    cfg = client.config

    graphql = cfg.api == "graphql"
    if graphql and flt.fields:
        logger.warning("--fields solo aplica a la API REST: con GraphQL se ignora.")
        flt = replace(flt, fields=None)
    contar = count_orders_graphql if graphql else count_orders

    logger.info(
        "Extrayendo pedidos de %s (%s %s) | status=%s | %s %s → %s",
        cfg.shop_domain,
        "GraphQL" if graphql else "REST",
        cfg.api_version,
        flt.status,
        flt.date_field,
        flt.date_min.isoformat(),
        flt.date_max.isoformat(),
    )
    expected = contar(client, flt)
    logger.info("Shopify reporta %d pedidos en la ventana.", expected)

    t0 = time.perf_counter()
    if graphql:
        # GraphQL trae la bodega en la misma consulta: no hay llamadas extra por pedido.
        orders = extract_orders_graphql(client, flt)
        enricher = None
    else:
        orders = extract_orders(client, flt)
        enricher = BodegaEnricher(client, debe_consultar_bodega) if consultar_bodega else None
        if enricher:
            orders = enricher.enrich(orders)
    written = write_jsonl(orders, output_file)
    duration = round(time.perf_counter() - t0, 2)

    recount = None
    if written != expected:
        # La ventana [date_min, date_max] quedó fija al iniciar, así que un pedido solo puede
        # SALIR de ella durante la corrida: se modificó (con updated_at su fecha pasa de
        # date_max) o se eliminó. Un segundo conteo lo confirma: si coincide con lo extraído,
        # la diferencia está explicada y la próxima corrida incremental recoge esos pedidos.
        # Si tampoco coincide, se perdió algo de verdad (p. ej. en la paginación).
        recount = contar(client, flt)
        logger.info("El conteo no cuadró (%d vs %d); segundo conteo: %d.", expected, written, recount)

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
        bodegas_consultadas=written if graphql else (enricher.enriched if enricher else 0),
        duration_seconds=duration,
        output_file=output_file.name,
        fields=list(flt.fields) if flt.fields else None,
        incremental=incremental,
        bodegas_omitidas=enricher.omitidos if enricher else 0,
        recount_count=recount,
        api=cfg.api,
    )
    _write_manifest(result, output_dir / f"{run_id}.manifest.json")

    logger.info("%d pedidos escritos en %s (%.1fs)", written, output_file, duration)
    if enricher and enricher.omitidos:
        logger.info(
            "Bodega: %d consultas, %d ahorradas (pedidos que no van al reporte).",
            enricher.enriched,
            enricher.omitidos,
        )
    if not result.reconciled:
        logger.warning(
            "Conciliación: Shopify reporta %d (segundo conteo: %s), se extrajeron %d. Investigar antes "
            "de cargar a Siesa.",
            expected,
            recount,
            written,
        )
    elif recount is not None:
        logger.info(
            "Conciliación: %d pedidos salieron de la ventana durante la corrida (modificados o "
            "eliminados); la próxima corrida los recoge.",
            expected - written,
        )
    return result


def _write_manifest(result: ExtractionResult, path: Path) -> None:
    write_json_atomic(asdict(result) | {"reconciled": result.reconciled}, path)
