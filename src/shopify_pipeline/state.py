"""
Estado entre corridas: lo que el pipeline necesita recordar de una ejecución a la otra.

QUÉ GUARDA (en ``data/state/``)
    watermark.json    Hasta qué momento quedó cubierta la última extracción completa.
                      El modo ``--incremental`` arranca desde ahí (menos un margen), así
                      que una corrida que falla, se retrasa o no se ejecuta NO deja huecos:
                      la siguiente retoma donde quedó la última buena.
    reportados.json   Pedidos que ya salieron en un reporte Siesa (id → total y corrida).
                      Como las ventanas se solapan a propósito, un mismo pedido aparece en
                      varias extracciones; este registro evita reportarlo dos veces.

POR QUÉ JSON Y NO UNA BASE DE DATOS
    El volumen es pequeño (cientos de pedidos al día) y la carpeta ``data/`` vive en Google
    Drive. Un archivo que se reemplaza completo de forma atómica es lo más seguro frente a
    la sincronización de Drive; una base SQLite a medio escribir podría subirse corrupta.

    Regla de operación: una sola máquina ejecuta la tarea programada. Si dos equipos
    escriben el estado al tiempo, Drive crea copias en conflicto ("reportados (1).json").
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shopify_pipeline.exceptions import DataError
from shopify_pipeline.sinks.atomic import write_json_atomic

logger = logging.getLogger(__name__)

DEFAULT_STATE_DIR = Path("data/state")
WATERMARK_FILE = "watermark.json"
LEDGER_FILE = "reportados.json"
LEDGER_SCHEMA_VERSION = 1

# Margen de solapamiento del modo incremental: cubre relojes desfasados y pedidos que
# Shopify indexa con unos segundos de retraso. Los repetidos los absorbe el ledger.
OVERLAP = timedelta(minutes=30)
# Ventana de la primera corrida incremental (cuando aún no hay watermark).
DIAS_PRIMERA_CORRIDA = 7


def _ahora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _leer_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DataError(f"No se pudo leer {path} ({exc}). Revíselo o restáurelo desde Drive.") from exc
    if not isinstance(data, dict):
        raise DataError(f"{path} no tiene el formato esperado.")
    return data


# ------------------------------------------------------------------ watermark
@dataclass(frozen=True)
class Watermark:
    date_max: datetime  # Fin de la ventana de la última extracción completa (UTC).
    run_id: str


def load_watermark(state_dir: Path = DEFAULT_STATE_DIR) -> Watermark | None:
    path = state_dir / WATERMARK_FILE
    if not path.exists():
        return None
    data = _leer_json(path)
    try:
        return Watermark(datetime.fromisoformat(data["date_max"]), str(data["run_id"]))
    except (KeyError, ValueError) as exc:
        raise DataError(f"{path} está dañado ({exc}).") from exc


def save_watermark(date_max: datetime, run_id: str, state_dir: Path = DEFAULT_STATE_DIR) -> None:
    payload = {"date_max": date_max.isoformat(), "run_id": run_id, "guardado_en": _ahora()}
    write_json_atomic(payload, state_dir / WATERMARK_FILE)
    logger.info("Watermark actualizado: %s (run %s).", date_max.isoformat(), run_id)


def incremental_window(
    state_dir: Path = DEFAULT_STATE_DIR, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Ventana ``[watermark - OVERLAP, ahora]``; sin watermark, los últimos 7 días."""
    now = now or datetime.now(timezone.utc).replace(microsecond=0)
    wm = load_watermark(state_dir)
    if wm is None:
        logger.info("Primera corrida incremental: se toman los últimos %d días.", DIAS_PRIMERA_CORRIDA)
        return now - timedelta(days=DIAS_PRIMERA_CORRIDA), now
    atraso = now - wm.date_max
    if atraso > timedelta(days=3):
        logger.warning(
            "La última extracción completa fue hace %s (run %s): se recupera todo el periodo.",
            atraso,
            wm.run_id,
        )
    return wm.date_max - OVERLAP, now


# --------------------------------------------------------------------- ledger
@dataclass(frozen=True)
class Reportado:
    total: str
    run_id: str
    fecha: str


class Ledger:
    """Registro de pedidos ya reportados a Siesa: ``{order_id: Reportado}``."""

    def __init__(self, path: Path, entradas: dict[str, Reportado] | None = None) -> None:
        self.path = path
        self._entradas = entradas or {}
        self._cambios = False

    @classmethod
    def open(cls, state_dir: Path = DEFAULT_STATE_DIR) -> Ledger:
        path = state_dir / LEDGER_FILE
        if not path.exists():
            return cls(path)
        data = _leer_json(path)
        version = data.get("schema_version")
        if version != LEDGER_SCHEMA_VERSION:
            raise DataError(
                f"{path}: versión {version!r} no soportada (se esperaba {LEDGER_SCHEMA_VERSION})."
            )
        try:
            entradas = {oid: Reportado(**e) for oid, e in data["pedidos"].items()}
        except (KeyError, TypeError) as exc:
            raise DataError(f"{path} está dañado ({exc}).") from exc
        return cls(path, entradas)

    def __len__(self) -> int:
        return len(self._entradas)

    def get(self, order_id: int | str) -> Reportado | None:
        return self._entradas.get(str(order_id))

    def marcar(self, order_id: int | str, total: str, run_id: str) -> None:
        self._entradas[str(order_id)] = Reportado(total=total, run_id=run_id, fecha=_ahora())
        self._cambios = True

    def save(self) -> None:
        if not self._cambios:
            return
        payload = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "pedidos": {oid: asdict(e) for oid, e in sorted(self._entradas.items())},
        }
        write_json_atomic(payload, self.path, indent=None)
        self._cambios = False
