"""Bitácora: run_id en cada línea y una línea de métricas estandarizada por etapa."""

import json
import logging
import re

import pytest

from shopify_pipeline import cli
from shopify_pipeline.logs import metricas_etapa, set_run_id
from tests.conftest import FIXTURES

METRICA = re.compile(
    r"^\S+ \S+ INFO run=(?P<run>\S+) shopify_pipeline\.metricas \| etapa=(?P<etapa>\w+) estado=ok "
    r"ok=(?P<ok>\d+) corruptas=(?P<corruptas>\d+) seg=\d+\.\d{2}(?P<extra>.*)$"
)


@pytest.fixture(autouse=True)
def _sin_run_id():
    yield
    set_run_id(None)


def test_metricas_etapa_ok(caplog):
    caplog.set_level(logging.INFO, logger="shopify_pipeline")
    with metricas_etapa("prueba") as m:
        m.ok, m.corruptas = 10, 2
        m.extra.update(lotes=3, costo=12.5)
    (registro,) = (r for r in caplog.records if r.name == "shopify_pipeline.metricas")
    assert registro.levelno == logging.INFO
    assert re.fullmatch(
        r"etapa=prueba estado=ok ok=10 corruptas=2 seg=\d+\.\d{2} lotes=3 costo=12\.50", registro.getMessage()
    )


def test_metricas_etapa_registra_el_fallo_y_no_lo_oculta(caplog):
    caplog.set_level(logging.INFO, logger="shopify_pipeline")
    with pytest.raises(RuntimeError), metricas_etapa("prueba") as m:
        m.ok = 4
        raise RuntimeError("falla")
    (registro,) = (r for r in caplog.records if r.name == "shopify_pipeline.metricas")
    assert registro.levelno == logging.ERROR
    assert "etapa=prueba estado=error ok=4" in registro.getMessage()


def test_todo_registro_trae_run_id():
    set_run_id("RUN-X")
    registro = logging.getLogger("cualquiera").makeRecord("x", logging.INFO, __file__, 1, "m", None, None)
    assert registro.run_id == "RUN-X"
    set_run_id(None)
    assert logging.getLogger("x").makeRecord("x", logging.INFO, __file__, 1, "m", None, None).run_id == "-"


def test_bitacora_de_una_corrida_real(tmp_path, monkeypatch):
    """La CLI deja run_id en cada línea y la métrica de la etapa en formato clave=valor."""
    monkeypatch.chdir(tmp_path)
    pedido = json.loads((FIXTURES / "order_1006.json").read_text(encoding="utf-8"))
    pedido["financial_status"] = "paid"
    raw = tmp_path / "20261020T120000Z.jsonl"
    raw.write_text(json.dumps(pedido) + "\n", encoding="utf-8")

    assert cli.main(["--env-file", "x.env", "transform", "--input", str(raw), "--sin-ledger"]) == cli.EXIT_OK

    (bitacora,) = (tmp_path / "data" / "logs").glob("shopify_pipeline_*.log")
    lineas = bitacora.read_text(encoding="utf-8").splitlines()
    assert " run=- shopify_pipeline | Inicio" in lineas[0]  # antes de conocer la corrida
    assert all(" run=" in linea for linea in lineas)
    (metrica,) = (m for linea in lineas if (m := METRICA.match(linea)))
    assert metrica["run"] == "20261020T120000Z"
    assert (metrica["etapa"], metrica["ok"], metrica["corruptas"]) == ("transform", "1", "0")
    assert "lineas=2" in metrica["extra"]
