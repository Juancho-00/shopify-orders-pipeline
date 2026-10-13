import argparse
import json
from datetime import datetime, timezone

import pytest
import responses

from shopify_pipeline import cli
from tests.conftest import BASE, SHOP


def _args(*argv):
    return cli.build_parser().parse_args(["extract", *argv])


def test_default_7_dias():
    f = cli.build_filter(_args())
    assert (f.created_at_max - f.created_at_min).days == 7
    assert f.status == "any"


def test_since_until():
    f = cli.build_filter(_args("--since", "2026-10-01", "--until", "2026-10-08T00:00:00-05:00"))
    assert f.created_at_min == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert f.created_at_max.utcoffset().total_seconds() == -5 * 3600


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
        ["--env-file", str(tmp_path / "x.env"), "extract", "--days", "3", "--output-dir", str(tmp_path)]
    )
    assert code == cli.EXIT_OK
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
        ["--env-file", str(tmp_path / "x.env"), "extract", "--strict", "--output-dir", str(tmp_path)]
    )
    assert code == cli.EXIT_UNRECONCILED


@responses.activate
def test_main_403_sale_con_2(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", SHOP)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
    responses.get(f"{BASE}/orders/count.json", status=403)
    code = cli.main(["--env-file", str(tmp_path / "x.env"), "extract", "--output-dir", str(tmp_path)])
    assert code == cli.EXIT_CONFIG
