"""
Genera el reporte de pedidos para Siesa a partir de un archivo crudo (JSONL).

No llama a Shopify: se puede re-ejecutar cuantas veces se quiera sobre una extracción
ya guardada (por ejemplo, después de ajustar una regla de mapeo).

Antes de transformar se lee el manifiesto de la extracción (``<run_id>.manifest.json``):

* Si la extracción se hizo con ``--fields`` y faltan campos críticos, se detiene
  (``DataError``): el reporte saldría incompleto sin que nadie lo note.
* Si el conteo no cuadró contra Shopify, se avisa en la bitácora.

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

from shopify_pipeline.exceptions import ConfigError, DataError
from shopify_pipeline.extract import MANIFEST_SCHEMA_VERSION
from shopify_pipeline.logs import metricas_etapa, set_run_id
from shopify_pipeline.sinks.tabular import write_csv, write_xlsx
from shopify_pipeline.state import Ledger
from shopify_pipeline.transform.alertas import EVENT_COLUMNS
from shopify_pipeline.transform.siesa_lines import (
    CLAVES_CRITICAS,
    COLUMNS,
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
    manifest: dict[str, Any] | None = None

    @property
    def reconciled(self) -> bool:
        """False solo si el manifiesto dice explícitamente que el conteo no cuadró."""
        return self.manifest is None or self.manifest.get("reconciled", True) is not False


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise DataError(f"{path.name}, línea {number}: JSON inválido ({exc})") from exc


def latest_raw_file(raw_dir: Path) -> Path:
    """Última extracción por nombre (el run_id es ordenable)."""
    files = sorted(p for p in raw_dir.glob("*.jsonl") if not p.name.startswith("."))
    if not files:
        raise ConfigError(f"No hay extracciones en {raw_dir}. Ejecute primero 'shopify-pipeline extract'.")
    return files[-1]


def manifest_path(raw_file: Path) -> Path:
    return raw_file.with_name(f"{raw_file.stem}.manifest.json")


def read_manifest(raw_file: Path) -> dict[str, Any] | None:
    """Lee y valida el manifiesto de una extracción. ``None`` si no existe."""
    path = manifest_path(raw_file)
    if not path.exists():
        logger.warning(
            "%s no tiene manifiesto: no se puede verificar si la extracción cuadró.", raw_file.name
        )
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DataError(f"Manifiesto ilegible {path.name}: {exc}") from exc

    version = manifest.get("schema_version", 1)  # Los manifiestos anteriores no traían versión.
    if version > MANIFEST_SCHEMA_VERSION:
        raise DataError(
            f"{path.name} tiene schema_version={version}; esta versión del pipeline entiende "
            f"hasta {MANIFEST_SCHEMA_VERSION}. Actualice el pipeline."
        )
    fields = manifest.get("fields")
    if fields:
        faltan = sorted(CLAVES_CRITICAS - set(fields))
        if faltan:
            raise DataError(
                f"La extracción {raw_file.stem} se hizo con --fields sin {faltan}. Con esos datos el "
                "reporte Siesa saldría incompleto: vuelva a extraer sin --fields."
            )
    if manifest.get("reconciled") is False:
        logger.warning(
            "La extracción %s no cuadró (Shopify %s, extraídos %s): revise antes de cargar a Siesa.",
            raw_file.stem,
            manifest.get("expected_count"),
            manifest.get("written_count"),
        )
    return manifest


def _resumen(conteo: Counter[str]) -> str:
    return ", ".join(f"{codigo}={n}" for codigo, n in conteo.most_common()) or "ninguna"


def run_transform(
    raw_file: Path,
    output_dir: Path = DEFAULT_PROCESSED_DIR,
    options: SiesaLinesOptions | None = None,
    log_dir: Path = DEFAULT_LOG_DIR,
    ledger: Ledger | None = None,
    sufijo: str = "",
) -> TransformRun:
    """
    Transforma un JSONL crudo y escribe reporte + log de alertas.

    Con ``ledger``, se excluyen los pedidos ya reportados en otras corridas y, una vez
    escritos los archivos, se registran los de esta corrida.

    ``sufijo`` se agrega al nombre de los archivos (p. ej. ``_revision``) para que un
    reporte de revisión no reemplace al reporte oficial de la corrida.
    """
    set_run_id(raw_file.stem)
    with metricas_etapa("transform") as metricas:
        run = _run_transform(raw_file, output_dir, options, log_dir, ledger, sufijo)
        r = run.result
        metricas.ok, metricas.corruptas = r.pedidos_procesados, r.errores
        metricas.extra.update(lineas=len(r.rows), excluidos=sum(r.pedidos_excluidos.values()) - r.errores)
    return run


def _run_transform(
    raw_file: Path,
    output_dir: Path,
    options: SiesaLinesOptions | None,
    log_dir: Path,
    ledger: Ledger | None,
    sufijo: str,
) -> TransformRun:
    manifest = read_manifest(raw_file)
    run_id = raw_file.stem
    result = transform_orders(read_jsonl(raw_file), options, ledger=ledger, run_id=run_id)
    csv_file = output_dir / f"pedidos_siesa_{run_id}{sufijo}.csv"
    xlsx_file = output_dir / f"pedidos_siesa_{run_id}{sufijo}.xlsx"
    alertas_file = log_dir / f"alertas_{run_id}{sufijo}.csv"

    write_csv(result.rows, csv_file, COLUMNS)
    write_xlsx(result.rows, xlsx_file, COLUMNS, NUMERIC_COLUMNS)
    # El log se escribe siempre (aunque esté vacío) para que cada corrida deje rastro.
    write_csv((e.as_row() for e in result.eventos), alertas_file, EVENT_COLUMNS)

    # Solo después de escribir el reporte: si algo falló antes, nada queda marcado.
    if ledger is not None:
        for order_id, total in result.reportados:
            ledger.marcar(order_id, total, run_id)
        ledger.save()

    logger.info(
        "Reporte Siesa: %d pedidos → %d líneas (%s).",
        result.pedidos_procesados,
        len(result.rows),
        xlsx_file,
    )
    logger.info("Pedidos excluidos: %s.", _resumen(Counter(result.pedidos_excluidos)))
    if result.errores:
        logger.error(
            "%d pedidos no se pudieron procesar (ERROR_TRANSFORMACION / DATOS_INCOMPLETOS / "
            "ESQUEMA_INVALIDO). Detalle en %s",
            result.errores,
            alertas_file,
        )
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
    return TransformRun(result, csv_file, xlsx_file, alertas_file, manifest)
