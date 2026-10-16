import json
from datetime import datetime, timedelta, timezone

import pytest

from shopify_pipeline.exceptions import DataError
from shopify_pipeline.state import (
    DIAS_PRIMERA_CORRIDA,
    LEDGER_FILE,
    OVERLAP,
    WATERMARK_FILE,
    Ledger,
    incremental_window,
    load_watermark,
    save_watermark,
)

NOW = datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ watermark
def test_sin_watermark_devuelve_none(tmp_path):
    assert load_watermark(tmp_path) is None


def test_watermark_ida_y_vuelta(tmp_path):
    save_watermark(NOW, "RUN1", tmp_path)
    wm = load_watermark(tmp_path)
    assert wm.date_max == NOW
    assert wm.run_id == "RUN1"
    assert not list(tmp_path.glob("*.tmp"))  # escritura atómica: no quedan temporales


def test_watermark_danado_es_error_de_datos(tmp_path):
    (tmp_path / WATERMARK_FILE).write_text("{no es json", encoding="utf-8")
    with pytest.raises(DataError):
        load_watermark(tmp_path)


def test_ventana_incremental_primera_corrida(tmp_path):
    date_min, date_max = incremental_window(tmp_path, now=NOW)
    assert date_max == NOW
    assert date_min == NOW - timedelta(days=DIAS_PRIMERA_CORRIDA)


def test_ventana_incremental_retoma_desde_el_watermark(tmp_path):
    """Aunque la tarea corra tarde (o un día después), no queda ningún hueco."""
    ultima = NOW - timedelta(days=2, minutes=7)
    save_watermark(ultima, "RUN1", tmp_path)
    date_min, date_max = incremental_window(tmp_path, now=NOW)
    assert date_min == ultima - OVERLAP
    assert date_max == NOW


# --------------------------------------------------------------------- ledger
def test_ledger_vacio(tmp_path):
    ledger = Ledger.open(tmp_path)
    assert len(ledger) == 0
    assert ledger.get(1) is None
    ledger.save()  # sin cambios no escribe nada
    assert not (tmp_path / LEDGER_FILE).exists()


def test_ledger_ida_y_vuelta(tmp_path):
    ledger = Ledger.open(tmp_path)
    ledger.marcar(5801, "102293.34", "RUN1")
    ledger.save()

    reabierto = Ledger.open(tmp_path)
    assert len(reabierto) == 1
    entrada = reabierto.get("5801")
    assert (entrada.total, entrada.run_id) == ("102293.34", "RUN1")
    data = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert data["schema_version"] == 1


def test_ledger_version_desconocida(tmp_path):
    (tmp_path / LEDGER_FILE).write_text('{"schema_version": 99, "pedidos": {}}', encoding="utf-8")
    with pytest.raises(DataError, match="versión"):
        Ledger.open(tmp_path)
