"""Fase 3: hoja Terceros de la plantilla de clientes. Datos ficticios."""

from __future__ import annotations

import pytest

from shopify_pipeline.erp.terceros import (
    TERCEROS_COLUMNS,
    fila_tercero,
    partir_texto,
    repartir_direccion,
)


@pytest.fixture
def pedido():
    """Una fila del reporte de la fase 1 (como se lee del CSV: todo texto)."""
    return {
        "tipo_documento": "C",
        "numero_documento": "1017000001",
        "primer_nombre": "Laura",
        "segundo_nombre": "Sofía",
        "primer_apellido": "Restrepo",
        "segundo_apellido": "de la Torre",
        "direccion": "Calle 10 # 20-30",
        "direccion_complemento": "Apto 301",
        "codigo_ciudad_siesa": "16905001",
        "telefono": "3001112233",
        "email": "cliente.prueba@example.com",
    }


def test_cedula(pedido):
    t = fila_tercero(pedido, "20261019")
    assert t.cargable and t.alertas == ()
    assert list(t.fila) == list(TERCEROS_COLUMNS)
    f = t.fila
    assert (f["F200_ID"], f["F200_NIT"], f["F200_ID_TIPO_IDENT"]) == ("1017000001", "1017000001", "C")
    assert f["F200_IND_TIPO_TERCERO"] == "1"
    assert f["F200_RAZON_SOCIAL"] == ""
    assert (f["F200_APELLIDO1"], f["F200_APELLIDO2"], f["F200_NOMBRES"]) == (
        "RESTREPO",
        "DE LA TORRE",
        "LAURA SOFÍA",
    )
    assert f["F015_CONTACTO"] == "RESTREPO DE LA TORRE LAURA SOFÍA"  # APELLIDOS NOMBRES
    assert (f["F015_DIRECCION1"], f["F015_DIRECCION2"], f["F015_DIRECCION3"]) == (
        "Calle 10 # 20-30",
        "",
        "Apto 301",
    )
    assert (f["F015_ID_PAIS"], f["F015_ID_DEPTO"], f["F015_ID_CIUDAD"]) == ("169", "05", "001")
    assert f["F015_TELEFONO"] == f["F015_CELULAR"] == "3001112233"  # sin indicativo 57
    assert f["F200_FECHA_NACIMIENTO"] == "20261019"


def test_nit_lleva_razon_social_de_company_y_sin_apellidos(pedido):
    pedido.update({"tipo_documento": "N", "numero_documento": "900123456",
                   "razon_social": "COMERCIAL ANDINA S.A.S."})  # fmt: skip
    f = fila_tercero(pedido, "20261019").fila
    assert f["F200_ID_TIPO_IDENT"] == "N"
    assert f["F200_RAZON_SOCIAL"] == f["F015_CONTACTO"] == "COMERCIAL ANDINA S.A.S."
    assert (f["F200_APELLIDO1"], f["F200_APELLIDO2"], f["F200_NOMBRES"]) == ("", "", "")


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("email", ""), ("email", "sin-arroba.com"), ("telefono", ""), ("telefono", "12345")],
)
def test_email_y_telefono_obligatorios(pedido, campo, valor):
    pedido[campo] = valor  # Se necesitan para la facturación electrónica.
    t = fila_tercero(pedido, "20261019")
    assert not t.cargable and campo in t.faltantes


@pytest.mark.parametrize("campo", ["numero_documento", "tipo_documento", "direccion", "codigo_ciudad_siesa"])
def test_falta_dato_obligatorio_no_es_cargable(pedido, campo):
    pedido[campo] = ""
    t = fila_tercero(pedido, "20261019")
    assert not t.cargable
    assert campo in t.faltantes


def test_partir_texto_no_corta_palabras():
    texto = "Carrera 43A # 1 Sur - 100 Edificio Torre Empresarial"
    assert partir_texto(texto) == ["Carrera 43A # 1 Sur - 100 Edificio Torre", "Empresarial"]
    assert all(len(t) <= 40 for t in partir_texto("x" * 95)) and len(partir_texto("x" * 95)) == 3


def test_direccion_larga_sigue_en_el_campo_2():
    d1, d2, d3, truncada = repartir_direccion(
        "Carrera 43A # 1 Sur - 100 Edificio Torre Empresarial", "Of 501"
    )
    assert (d1, d2, d3, truncada) == (
        "Carrera 43A # 1 Sur - 100 Edificio Torre",
        "Empresarial",
        "Of 501",
        False,
    )


def test_complemento_largo_usa_el_campo_2_si_esta_libre():
    comp = "Casa dos pisos blanca escaleras afuera frente al parque"
    d1, d2, d3, truncada = repartir_direccion("Calle 1 # 2-3", comp)
    assert (d1, d2, d3, truncada) == (
        "Calle 1 # 2-3",
        "Casa dos pisos blanca escaleras afuera",
        "frente al parque",
        False,
    )


def test_direccion_que_no_cabe_genera_alerta(pedido):
    pedido["direccion"] = " ".join(["Palabra"] * 20)  # ~160 caracteres
    t = fila_tercero(pedido, "20261019")
    assert t.alertas == ("DIRECCION_TRUNCADA",)
    assert all(len(t.fila[c]) <= 40 for c in ("F015_DIRECCION1", "F015_DIRECCION2", "F015_DIRECCION3"))


@pytest.mark.parametrize("telefono", ["+57 300 111 2233", "573001112233", "300 111 2233"])
def test_telefono_sin_indicativo(pedido, telefono):
    pedido["telefono"] = telefono
    f = fila_tercero(pedido, "20261019").fila
    assert f["F015_TELEFONO"] == f["F015_CELULAR"] == "3001112233"


def test_pais_siempre_169(pedido):
    pedido["codigo_ciudad_siesa"] = "16911001"
    f = fila_tercero(pedido, "20261019").fila
    assert (f["F015_ID_PAIS"], f["F015_ID_DEPTO"], f["F015_ID_CIUDAD"], f["F015_ID_BARRIO"]) == (
        "169",
        "11",
        "001",
        "",
    )
