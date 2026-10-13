"""Sink a archivos JSON Lines con escritura atómica."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def write_jsonl(records: Iterable[dict[str, Any]], path: Path) -> int:
    """
    Escribe en un archivo temporal y lo renombra al final (``os.replace`` es atómico).
    Si la extracción falla a mitad de camino, no queda un archivo parcial.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return count


class JsonlSink:
    """Envoltorio de ``write_jsonl`` que cumple el protocolo ``Sink``."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, records: Iterable[dict[str, Any]]) -> int:
        return write_jsonl(records, self.path)
