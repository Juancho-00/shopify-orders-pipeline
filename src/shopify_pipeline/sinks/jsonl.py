"""
Escritura a JSON Lines (``.jsonl``): un objeto JSON por línea.

Se usa para la zona cruda porque guarda cada pedido exactamente como lo entrega Shopify
y se puede leer línea por línea sin cargar todo el archivo en memoria.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shopify_pipeline.sinks.atomic import atomic_target


def write_jsonl(records: Iterable[dict[str, Any]], path: Path) -> int:
    """
    Escribe en un archivo temporal y lo renombra al final (ver ``atomic.py``).
    Si la extracción falla a mitad de camino, no queda un archivo parcial.
    """
    count = 0
    with atomic_target(path) as tmp, tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count
