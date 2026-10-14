"""
Configuración de la bitácora (logs) del pipeline.

QUÉ HACE
    Hace que cada mensaje (``logger.info``, ``logger.warning``...) salga en dos lugares:

    * la consola, para verlo mientras corre;
    * el archivo ``data/logs/shopify_pipeline_AAAAMMDD.log``, para revisarlo después.
      Todas las ejecuciones del mismo día se agregan al final del mismo archivo.

    Cada archivo .py crea su propio ``logger = logging.getLogger(__name__)``. Como todos
    cuelgan de ``shopify_pipeline``, basta configurar ese logger "padre" una vez aquí.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"
_MARCA = "_shopify_pipeline"  # Identifica el manejador de archivo que agregamos nosotros.


def setup_logging(level: str, log_dir: Path | None) -> Path | None:
    """Configura consola + archivo diario. Devuelve la ruta del archivo (o None)."""
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT)
    pkg = logging.getLogger("shopify_pipeline")
    pkg.setLevel(level.upper())

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
