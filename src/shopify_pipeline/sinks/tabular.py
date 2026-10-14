"""
Sinks tabulares: CSV (para sistemas) y Excel (para revisión humana).

* CSV: UTF-8 con BOM, separador ``,`` y punto decimal. Es el formato estable para
  cargas automáticas.
* Excel: los montos se guardan como números reales, así que se ven bien sin importar
  la configuración regional del equipo (en Colombia, Excel usa coma decimal y abriría
  mal un CSV con punto decimal).

Ambos se escriben de forma atómica (temporal + renombrar).
"""

from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Iterable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any


def _atomic_target(path: Path) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    return tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")


def write_csv(rows: Iterable[dict[str, Any]], path: Path, columns: Sequence[str]) -> int:
    fd, tmp_name = _atomic_target(path)
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
                count += 1
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return count


def write_xlsx(
    rows: Sequence[dict[str, Any]],
    path: Path,
    columns: Sequence[str],
    numeric_columns: frozenset[str] = frozenset(),
    sheet_title: str = "Pedidos",
) -> int:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(list(columns))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        values = []
        for col in columns:
            value = row.get(col, "")
            if col in numeric_columns and isinstance(value, Decimal):
                value = float(value)
            values.append(value)
        ws.append(values)

    for idx, col in enumerate(columns, start=1):
        width = max([len(col)] + [len(str(r.get(col, ""))) for r in rows[:200]]) + 2
        ws.column_dimensions[get_column_letter(idx)].width = min(width, 50)
        if col in numeric_columns and col not in {"cantidad", "tasa_iva"}:
            for (cell,) in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                cell.number_format = "#,##0.00"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    fd, tmp_name = _atomic_target(path)
    os.close(fd)
    try:
        wb.save(tmp_name)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return len(rows)
