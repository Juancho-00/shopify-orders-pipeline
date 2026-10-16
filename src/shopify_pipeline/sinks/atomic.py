"""
Escritura atómica: primero a un archivo temporal en la misma carpeta y, solo si todo salió
bien, se renombra al nombre final (``os.replace`` es atómico en el mismo disco).

Si algo falla a mitad de camino, el temporal se borra y el archivo final queda como
estaba: nunca un archivo a medias que la siguiente etapa lea como si estuviera completo.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def atomic_target(path: Path) -> Iterator[Path]:
    """
    Entrega la ruta de un temporal; al salir del bloque sin error lo renombra a ``path``.

        with atomic_target(destino) as tmp, tmp.open("w", encoding="utf-8") as fh:
            fh.write(...)

    El archivo debe cerrarse dentro del bloque (en Windows no se puede renombrar un
    archivo abierto); con ``with a, b`` Python cierra ``b`` antes de terminar ``a``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        yield tmp
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json_atomic(data: Any, path: Path, indent: int | None = 2) -> None:
    """Escribe un JSON en UTF-8 de forma atómica (indentado por defecto; ``None`` = compacto)."""
    with atomic_target(path) as tmp:
        tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
