"""Contrato común de los sinks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol


class Sink(Protocol):
    """Destino de registros. Debe ser idempotente o atómico."""

    def write(self, records: Iterable[dict[str, Any]]) -> int:
        """Escribe los registros y devuelve la cantidad escrita."""
        ...
