import argparse
import csv
import json
import os
from datetime import datetime, timezone

import pytest
import responses

from shopify_pipeline import cli
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
    assert f.date_min == datetime(2026, 10, 1, tzinfo=timezone.utc)
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


def test_fields():
    f = cli.build_filter(_args("--fields", "name, total_price"))
    assert f.fields == ("id", "name", "total_price")


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
