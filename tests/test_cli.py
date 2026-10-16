import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import responses

from shopify_pipeline import cli, extract
from shopify_pipeline.state import OVERLAP, load_watermark
from shopify_pipeline.transform.siesa_lines import CAMPOS_REQUERIDOS
from tests.conftest import BASE, FIXTURES, SHOP


@pytest.fixture(autouse=True)
def _en_carpeta_temporal(tmp_path, monkeypatch):
    """La CLI escribe en rutas relativas (data/...): cada prueba corre en una carpeta vacía."""
    monkeypatch.chdir(tmp_path)


def _args(*argv):
    return cli.build_parser().parse_args(["extract", *argv])


def test_default_7_dias():
    f = cli.build_filter(_args())
    assert (f.date_max - f.date_min).days == 7
    assert f.status == "any"


def test_since_until():
    f = cli.build_filter(_args("--since", "2026-10-01", "--until", "2026-10-08T00:00:00-05:00"))
    assert f.date_min == datetime(2026, 10, 1, 5, tzinfo=timezone.utc)  # 00:00 en Colombia
    assert f.date_max.utcoffset().total_seconds() == -5 * 3600


def test_until_sin_since_falla():
    with pytest.raises(ValueError):
        cli.build_filter(_args("--until", "2026-10-08"))


def test_days_y_since_son_excluyentes():
    with pytest.raises(SystemExit):
        _args("--days", "3", "--since", "2026-10-01")


def test_fecha_sin_zona_horaria_se_rechaza():
    with pytest.raises(argparse.ArgumentTypeError):
        cli._parse_date("2026-10-01T10:00:00")


def test_fields_con_solo_raw_respeta_la_proyeccion():
    f = cli.build_filter(_args("--fields", "name, total_price", "--solo-raw"))
    assert f.fields == ("id", "name", "total_price")


def test_fields_agrega_campos_que_necesita_el_reporte():
    f = cli.build_filter(_args("--fields", "name, total_price"))
    assert f.fields[:2] == ("name", "total_price")
    assert set(CAMPOS_REQUERIDOS) <= set(f.fields)
    assert len(f.fields) == len(set(f.fields))  # sin duplicados


def test_main_sin_credenciales_sale_con_2(tmp_path):
    code = cli.main(["--env-file", str(tmp_path / "no-existe.env"), "extract"])
    assert code == cli.EXIT_CONFIG


@responses.activate
def test_main_extract_ok(monkeypatch, tmp_path, orders_page):
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", SHOP)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
    responses.get(f"{BASE}/orders/count.json", json={"count": 2})
    responses.get(f"{BASE}/orders.json", json=orders_page)

    code = cli.main(
        [
            "--env-file", str(tmp_path / "x.env"), "extract", "--days", "3", "--sin-bodega",
            "--output-dir", str(tmp_path), "--processed-dir", str(tmp_path / "siesa"),
        ]
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert len(list((tmp_path / "siesa").glob("pedidos_siesa_*.xlsx"))) == 1
    manifests = list(tmp_path.glob("*.manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text(encoding="utf-8"))["written_count"] == 2


@responses.activate
def test_main_strict_descuadre_sale_con_3(monkeypatch, tmp_path, orders_page):
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", SHOP)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
    responses.get(f"{BASE}/orders/count.json", json={"count": 99})
    responses.get(f"{BASE}/orders.json", json=orders_page)

    code = cli.main(
        [
            "--env-file",
            str(tmp_path / "x.env"),
            "extract",
            "--strict",
            "--sin-bodega",
            "--solo-raw",
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert code == cli.EXIT_UNRECONCILED


@responses.activate
def test_main_403_sale_con_2(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", SHOP)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
    responses.get(f"{BASE}/orders/count.json", status=403)
    code = cli.main(["--env-file", str(tmp_path / "x.env"), "extract", "--output-dir", str(tmp_path)])
    assert code == cli.EXIT_CONFIG


@responses.activate
def test_extract_end_to_end_pedido_1006(monkeypatch, tmp_path):
    """Pedido real (anonimizado) → JSONL con bodega → reporte Siesa con 2 líneas."""
    order = json.loads((FIXTURES / "order_1006.json").read_text(encoding="utf-8"))
    order["financial_status"] = "paid"
    fos = json.loads((FIXTURES / "fulfillment_orders_1006.json").read_text(encoding="utf-8"))
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", SHOP)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
    responses.get(f"{BASE}/orders/count.json", json={"count": 1})
    responses.get(f"{BASE}/orders.json", json={"orders": [order]})
    responses.get(f"{BASE}/orders/{order['id']}/fulfillment_orders.json", json=fos)

    code = cli.main(
        [
            "--env-file", str(tmp_path / "x.env"), "extract", "--codigo-envio", "FLETE",
            "--output-dir", str(tmp_path / "raw"), "--processed-dir", str(tmp_path / "siesa"),
        ]
    )  # fmt: skip
    assert code == cli.EXIT_OK
    (csv_file,) = (tmp_path / "siesa").glob("*.csv")
    with csv_file.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [(r["referencia"], r["bodega"]) for r in rows] == [
        ("KITK0108", "Bodega Principal Medellín"),
        ("FLETE", ""),
    ]
    assert rows[0]["numero_documento"] == "1017000001"


def test_transform_sin_extracciones(tmp_path):
    code = cli.main(["--env-file", str(tmp_path / "x.env"), "transform", "--raw-dir", str(tmp_path)])
    assert code == cli.EXIT_CONFIG


def test_codigo_envio_desde_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SIESA_CODIGO_ENVIO=FLETE99\n", encoding="utf-8")
    try:
        cli.main(["--env-file", str(env), "transform", "--raw-dir", str(tmp_path)])
        assert cli.build_parser().parse_args(["transform"]).codigo_envio == "FLETE99"
    finally:
        os.environ.pop("SIESA_CODIGO_ENVIO", None)


def test_filtrar_por_actualizacion():
    f = cli.build_filter(_args("--filtrar-por", "actualizacion"))
    assert f.date_field == "updated_at"
    assert cli.build_filter(_args()).date_field == "created_at"


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("paid,partially_refunded", frozenset({"paid", "partially_refunded"})),
        (" PAID ", frozenset({"paid"})),
        ("todos", None),
    ],
)
def test_parse_estados(valor, esperado):
    assert cli._parse_estados(valor) == esperado


def test_estados_pago_vacio_falla():
    with pytest.raises(ValueError):
        cli._parse_estados(" , ")


@responses.activate
def test_logs_por_defecto_en_data_logs(monkeypatch, tmp_path, orders_page):
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", SHOP)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
    responses.get(f"{BASE}/orders/count.json", json={"count": 2})
    responses.get(f"{BASE}/orders.json", json=orders_page)

    code = cli.main(["--env-file", "x.env", "extract", "--days", "1", "--sin-bodega"])

    assert code == cli.EXIT_OK
    logs = tmp_path / "data" / "logs"
    (bitacora,) = logs.glob("shopify_pipeline_*.log")
    assert "Inicio: shopify-pipeline" in bitacora.read_text(encoding="utf-8")
    (alertas,) = logs.glob("alertas_*.csv")
    contenido = alertas.read_text(encoding="utf-8-sig")
    assert "CANCELADO" in contenido  # El #1002 de orders_page está cancelado


# --------------------------------------------------------------- incremental
def _env(monkeypatch):
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", SHOP)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")


def _pedido_1006_pagado() -> dict:
    order = json.loads((FIXTURES / "order_1006.json").read_text(encoding="utf-8"))
    return order | {"financial_status": "paid"}


def _extract_incremental(tmp_path, *extra):
    return cli.main(
        ["--env-file", str(tmp_path / "x.env"), "extract", "--incremental", "--sin-bodega", *extra]
    )


@responses.activate
def test_incremental_guarda_watermark_y_no_repite_pedidos(monkeypatch, tmp_path):
    _env(monkeypatch)
    run_ids = iter(["20261016T120000Z", "20261017T120000Z"])
    monkeypatch.setattr(extract, "new_run_id", lambda: next(run_ids))
    responses.get(f"{BASE}/orders/count.json", json={"count": 1})
    responses.get(f"{BASE}/orders.json", json={"orders": [_pedido_1006_pagado()]})

    assert _extract_incremental(tmp_path) == cli.EXIT_OK
    wm = load_watermark(Path("data/state"))
    assert wm is not None
    # La ventana va sobre updated_at
    assert "updated_at_min" in responses.calls[0].request.url

    # Segunda corrida: arranca en el watermark menos el solape y el pedido no se repite.
    assert _extract_incremental(tmp_path) == cli.EXIT_OK
    segunda = responses.calls[2].request.url
    esperado = (wm.date_max - OVERLAP).isoformat()
    assert f"updated_at_min={esperado}".replace(":", "%3A").replace("+", "%2B") in segunda

    reportes = sorted(Path("data/processed/siesa").glob("*.csv"))
    assert len(reportes) == 2
    with reportes[-1].open(encoding="utf-8-sig", newline="") as fh:
        assert list(csv.DictReader(fh)) == []  # Ya reportado en la corrida anterior
    alertas = Path("data/logs/alertas_20261017T120000Z.csv").read_text(encoding="utf-8-sig")
    assert "YA_REPORTADO" in alertas


@responses.activate
def test_incremental_sin_cuadrar_no_avanza_el_watermark(monkeypatch, tmp_path):
    _env(monkeypatch)
    responses.get(f"{BASE}/orders/count.json", json={"count": 5})
    responses.get(f"{BASE}/orders.json", json={"orders": [_pedido_1006_pagado()]})

    assert _extract_incremental(tmp_path, "--strict") == cli.EXIT_UNRECONCILED
    assert load_watermark(Path("data/state")) is None


def test_incremental_excluye_days_y_since():
    with pytest.raises(SystemExit):
        _args("--incremental", "--days", "2")


# ----------------------------------------------------------- códigos de salida
def test_transform_jsonl_danado_sale_con_4(tmp_path):
    raw = tmp_path / "20261016T120000Z.jsonl"
    raw.write_text("{malo\n", encoding="utf-8")
    code = cli.main(["--env-file", str(tmp_path / "x.env"), "transform", "--input", str(raw)])
    assert code == cli.EXIT_DATA


def test_transform_strict_con_pedido_malo_sale_con_4(tmp_path):
    malo = _pedido_1006_pagado()
    malo["line_items"][0]["price"] = "abc"
    raw = tmp_path / "20261016T120000Z.jsonl"
    raw.write_text(json.dumps(malo) + "\n", encoding="utf-8")
    base = ["--env-file", str(tmp_path / "x.env"), "transform", "--input", str(raw), "--sin-ledger"]

    assert cli.main(base) == cli.EXIT_OK  # Sin --strict: el error queda en el log de alertas
    assert cli.main([*base, "--strict"]) == cli.EXIT_DATA


def test_ledger_danado_sale_con_4_sin_llamar_a_shopify(monkeypatch, tmp_path):
    _env(monkeypatch)
    state = Path("data/state")
    state.mkdir(parents=True)
    (state / "reportados.json").write_text("{malo", encoding="utf-8")
    # Sin mocks de `responses`: si llamara a Shopify, la prueba fallaría con error de red.
    assert cli.main(["--env-file", str(tmp_path / "x.env"), "extract"]) == cli.EXIT_DATA


@pytest.mark.parametrize(
    ("error", "esperado"),
    [
        (PermissionError("pedidos.xlsx está abierto en Excel"), cli.EXIT_TRANSIENT),
        (RuntimeError("bug"), cli.EXIT_UNEXPECTED),
        (KeyError("id"), cli.EXIT_UNEXPECTED),
    ],
)
def test_errores_no_previstos_tienen_codigo_propio(monkeypatch, tmp_path, error, esperado):
    _env(monkeypatch)

    def falla(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli, "run_extraction", falla)
    assert cli.main(["--env-file", str(tmp_path / "x.env"), "extract"]) == esperado


def test_sin_ledger_no_reemplaza_el_reporte_oficial(tmp_path):
    raw = tmp_path / "20261016T120000Z.jsonl"
    raw.write_text(json.dumps(_pedido_1006_pagado()) + "\n", encoding="utf-8")
    base = ["--env-file", str(tmp_path / "x.env"), "transform", "--input", str(raw)]

    assert cli.main(base) == cli.EXIT_OK
    assert cli.main([*base, "--sin-ledger"]) == cli.EXIT_OK

    nombres = sorted(p.name for p in Path("data/processed/siesa").glob("*.csv"))
    assert nombres == ["pedidos_siesa_20261016T120000Z.csv", "pedidos_siesa_20261016T120000Z_revision.csv"]


@responses.activate
def test_extract_solo_consulta_bodega_de_pedidos_elegibles(monkeypatch, tmp_path):
    _env(monkeypatch)
    pagado = _pedido_1006_pagado()
    pendiente = pagado | {"id": 2, "name": "#1007", "order_number": 1007, "financial_status": "pending"}
    responses.get(f"{BASE}/orders/count.json", json={"count": 2})
    responses.get(f"{BASE}/orders.json", json={"orders": [pagado, pendiente]})
    responses.get(f"{BASE}/orders/{pagado['id']}/fulfillment_orders.json", json={"fulfillment_orders": []})

    assert cli.main(["--env-file", str(tmp_path / "x.env"), "extract"]) == cli.EXIT_OK

    llamadas_bodega = [c for c in responses.calls if "fulfillment_orders" in c.request.url]
    assert len(llamadas_bodega) == 1  # El pendiente no gasta llamada
    (manifest,) = Path("data/raw/shopify/orders").glob("*.manifest.json")
    datos = json.loads(manifest.read_text(encoding="utf-8"))
    assert (datos["bodegas_consultadas"], datos["bodegas_omitidas"]) == (1, 1)


def test_fecha_sola_es_medianoche_en_colombia():
    assert cli._parse_date("2026-10-01").isoformat() == "2026-10-01T00:00:00-05:00"
    # Con zona horaria explícita se respeta tal cual
    assert cli._parse_date("2026-10-01T00:00:00+00:00").utcoffset().total_seconds() == 0
