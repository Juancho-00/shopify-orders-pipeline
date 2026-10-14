from decimal import Decimal

import pytest

from shopify_pipeline.transform.normalize import (
    calcular_dv_nit,
    clean_text,
    normalize_phone,
    parse_documento,
    split_apellidos,
    split_nombres,
    to_bogota,
    to_decimal,
)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Mayerline", ("Mayerline", "")),
        ("Juan Pablo", ("Juan", "Pablo")),
        ("  maría   josé  ", ("maría", "josé")),
        ("Ana María Lucía", ("Ana", "María Lucía")),
        (None, ("", "")),
    ],
)
def test_split_nombres(entrada, esperado):
    assert split_nombres(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Lozano Gutierrez", ("Lozano", "Gutierrez")),
        ("Quintero", ("Quintero", "")),
        ("De la Torre Gómez", ("De la Torre", "Gómez")),
        ("Restrepo de la Torre", ("Restrepo", "de la Torre")),
        ("Del Valle San Martín", ("Del Valle", "San Martín")),
        ("Gómez de", ("Gómez de", "")),
        ("", ("", "")),
    ],
)
def test_split_apellidos(entrada, esperado):
    assert split_apellidos(entrada) == esperado


def test_dv_nit_dian():
    # NIT de la DIAN: 800.197.268-4
    assert calcular_dv_nit("800197268") == "4"


@pytest.mark.parametrize(
    ("entrada", "tipo", "numero", "dv", "alertas"),
    [
        ("1152469156", "CC", "1152469156", "", ()),
        ("1.152.469.156", "CC", "1152469156", "", ()),
        ("CC 43123456", "CC", "43123456", "", ()),
        ("C.C. 43.123.456", "CC", "43123456", "", ()),
        ("800197268", "NIT", "800197268", "4", ("NIT_POR_VERIFICAR",)),
        ("800.197.268-4", "NIT", "800197268", "4", ()),
        ("800197268-9", "NIT", "800197268", "9", ("DV_NIT_INVALIDO",)),
        ("NIT 800197268", "NIT", "800197268", "4", ()),
        ("CE 123456", "CE", "123456", "", ()),
        ("", "", "", "", ("SIN_DOCUMENTO",)),
        (None, "", "", "", ("SIN_DOCUMENTO",)),
        ("123", "CC", "123", "", ("DOCUMENTO_INVALIDO",)),
        ("abc", "CC", "", "", ("DOCUMENTO_INVALIDO",)),
    ],
)
def test_parse_documento(entrada, tipo, numero, dv, alertas):
    doc = parse_documento(entrada)
    assert (doc.tipo, doc.numero, doc.dv, doc.alertas) == (tipo, numero, dv, alertas)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("+573235016059", "3235016059"),
        ("+57 323 501 6059", "3235016059"),
        ("3235016059", "3235016059"),
        ("(604) 444 5555", "6044445555"),
        (None, ""),
    ],
)
def test_normalize_phone(entrada, esperado):
    assert normalize_phone(entrada) == esperado


def test_to_decimal():
    assert to_decimal("12294.34") == Decimal("12294.34")
    assert to_decimal("89999") == Decimal("89999.00")
    assert to_decimal(None) == Decimal("0.00")
    with pytest.raises(ValueError):
        to_decimal("abc")


def test_to_bogota():
    assert to_bogota("2026-10-08T17:59:15-05:00") == "2026-10-08 17:59:15"
    assert to_bogota("2026-10-08T22:59:15Z") == "2026-10-08 17:59:15"
    assert to_bogota(None) == ""


def test_clean_text_quita_saltos():
    assert clean_text("Entregar\nen portería\t ") == "Entregar en portería"
