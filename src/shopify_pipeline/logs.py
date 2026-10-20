"""
Configuración de la bitácora (logs) del pipeline.

QUÉ HACE
    Hace que cada mensaje (``logger.info``, ``logger.warning``...) salga en dos lugares:

    * la consola, para verlo mientras corre;
    * el archivo ``data/logs/shopify_pipeline_AAAAMMDD.log``, para revisarlo después.
      Todas las ejecuciones del mismo día se agregan al final del mismo archivo.

    Cada archivo .py crea su propio ``logger = logging.getLogger(__name__)``. Como todos
    cuelgan de ``shopify_pipeline``, basta configurar ese logger "padre" una vez aquí.

RUN_ID EN CADA LÍNEA
    Como el archivo diario mezcla varias corridas, cada línea lleva ``run=<run_id>``
    (``run=-`` antes de que la corrida tenga identificador). Lo fija ``set_run_id``.

MÉTRICAS POR ETAPA
    ``metricas_etapa`` deja UNA línea estandarizada por etapa, en formato ``clave=valor``
    para poder filtrarla o graficarla::

        ... INFO run=20261020T151331Z shopify_pipeline.metricas |
            etapa=extract estado=ok ok=300 corruptas=0 seg=41.20 lotes=40      (en una sola línea)

    ``ok`` = registros procesados con éxito; ``corruptas`` = registros descartados por datos
    inesperados o inválidos; ``seg`` = duración de la etapa.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

LOG_FORMAT = "%(asctime)s %(levelname)s run=%(run_id)s %(name)s | %(message)s"
_MARCA = "_shopify_pipeline"  # Identifica el manejador de archivo que agregamos nosotros.
SIN_RUN_ID = "-"

_run_id = SIN_RUN_ID
_fabrica_original = logging.getLogRecordFactory()


def _fabrica(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """Todo registro de log trae ``run_id`` (así ningún formato falla por falta del campo)."""
    record = _fabrica_original(*args, **kwargs)
    record.run_id = _run_id
    return record


logging.setLogRecordFactory(_fabrica)


def set_run_id(run_id: str | None) -> None:
    """Fija el identificador de corrida que llevarán las siguientes líneas de log."""
    global _run_id
    _run_id = run_id or SIN_RUN_ID


def setup_logging(level: str, log_dir: Path | None) -> Path | None:
    """Configura consola + archivo diario. Devuelve la ruta del archivo (o None)."""
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT)
    pkg = logging.getLogger("shopify_pipeline")
    pkg.setLevel(level.upper())
    set_run_id(None)

    # Si main() se llama varias veces en el mismo proceso (p. ej. en las pruebas), se quita
    # el archivo anterior para no escribir dos veces cada mensaje.
    for handler in [h for h in pkg.handlers if getattr(h, _MARCA, False)]:
        pkg.removeHandler(handler)
        handler.close()

    if log_dir is None:
        return None
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"shopify_pipeline_{date.today():%Y%m%d}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    setattr(handler, _MARCA, True)
    pkg.addHandler(handler)
    return path


# ------------------------------------------------------------------ métricas
_metricas_logger = logging.getLogger("shopify_pipeline.metricas")


@dataclass
class Metricas:
    """Contadores que la etapa va llenando; se registran al salir de ``metricas_etapa``."""

    etapa: str
    ok: int = 0
    corruptas: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _valor(v: Any) -> str:
    return f"{v:.2f}" if isinstance(v, float) else str(v)


@contextmanager
def metricas_etapa(etapa: str) -> Iterator[Metricas]:
    """
    Mide una etapa y deja su línea de métricas, también si falla (``estado=error``)::

        with metricas_etapa("transform") as m:
            ...
            m.ok, m.corruptas = procesados, descartados
            m.extra["lineas"] = len(filas)
    """
    m = Metricas(etapa)
    t0 = time.perf_counter()
    estado = "ok"
    try:
        yield m
    except BaseException:
        estado = "error"
        raise
    finally:
        extras = "".join(f" {k}={_valor(v)}" for k, v in m.extra.items())
        _metricas_logger.log(
            logging.INFO if estado == "ok" else logging.ERROR,
            "etapa=%s estado=%s ok=%d corruptas=%d seg=%.2f%s",
            etapa,
            estado,
            m.ok,
            m.corruptas,
            time.perf_counter() - t0,
            extras,
        )
