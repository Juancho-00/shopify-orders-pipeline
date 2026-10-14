"""
Genera el reporte de pedidos para Siesa a partir de un archivo crudo (JSONL).

No llama a Shopify: se puede re-ejecutar cuantas veces se quiera sobre una extracción
ya guardada (por ejemplo, después de ajustar una regla de mapeo).

Salida:
    data/processed/siesa/pedidos_siesa_<run_id>.csv    # para cargas automáticas
    data/processed/siesa/pedidos_siesa_<run_id>.xlsx   # para revisión en Excel
    data/logs/alertas_<run_id>.csv                     # alertas y pedidos excluidos
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shopify_pipeline.sinks.tabular import write_csv, write_xlsx
from shopify_pipeline.transform.siesa_lines import (
    COLUMNS,
    EVENT_COLUMNS,
    NUMERIC_COLUMNS,
    SiesaLinesOptions,
    TransformResult,
    transform_orders,
)

logger = logging.getLogger(__name__)

DEFAULT_PROCESSED_DIR = Path("data/processed/siesa")
DEFAULT_LOG_DIR = Path("data/logs")


@dataclass(frozen=True)
class TransformRun:
    result: TransformResult
    csv_file: Path
    xlsx_file: Path
    alertas_file: Path


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path.name}, línea {number}: JSON inválido ({exc})") from exc


def latest_raw_file(raw_dir: Path) -> Path:
    """Última extracción por nombre (el run_id es ordenable)."""
    files = sorted(p for p in raw_dir.glob("*.jsonl") if not p.name.startswith("."))
    if not files:
        raise ValueError(f"No hay extracciones en {raw_dir}. Ejecute primero 'shopify-pipeline extract'.")
    return files[-1]


def _resumen(conteo: Counter[str]) -> str:
    return ", ".join(f"{codigo}={n}" for codigo, n in conteo.most_common()) or "ninguna"


def run_transform(
    raw_file: Path,
    output_dir: Path = DEFAULT_PROCESSED_DIR,
    options: SiesaLinesOptions | None = None,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> TransformRun:
    result = transform_orders(read_jsonl(raw_file), options)
    run_id = raw_file.stem
    csv_file = output_dir / f"pedidos_siesa_{run_id}.csv"
    xlsx_file = output_dir / f"pedidos_siesa_{run_id}.xlsx"
    alertas_file = log_dir / f"alertas_{run_id}.csv"

    write_csv(result.rows, csv_file, COLUMNS)
    write_xlsx(result.rows, xlsx_file, COLUMNS, NUMERIC_COLUMNS)
    # El log se escribe siempre (aunque esté vacío) para que cada corrida deje rastro.
    write_csv((e.as_row() for e in result.eventos), alertas_file, EVENT_COLUMNS)

    logger.info(
        "Reporte Siesa: %d pedidos → %d líneas (%s).",
        result.pedidos_procesados,
        len(result.rows),
        xlsx_file,
    )
    logger.info("Pedidos excluidos: %s.", _resumen(Counter(result.pedidos_excluidos)))
    alertas = Counter(e.codigo for e in result.alertas)
    if alertas:
        logger.warning(
            "%d pedidos con alertas (%s). Detalle en %s",
            result.pedidos_con_alertas,
            _resumen(alertas),
            alertas_file,
        )
    else:
        logger.info("Sin alertas.")
    return TransformRun(result, csv_file, xlsx_file, alertas_file)
