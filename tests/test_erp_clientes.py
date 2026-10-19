"""Fase 3: hojas Clientes, Imptos y Reten y Ent. Dinamica Cliente. Datos ficticios."""

from __future__ import annotations

import pytest

from shopify_pipeline.erp.clientes import CLIENTES_COLUMNS, fila_cliente, fila_entidad, filas_impuestos


@pytest.fixture
def tercero():
    """Fila ya calculada de la hoja Terceros."""
    return {
        "F200_ID": "1017000001",
        "F015_CONTACTO": "LAURA RESTREPO",
        "F015_DIRECCION1": "Calle 10 # 20-30",
        "F015_DIRECCION2": "",
        "F015_DIRECCION3": "Apto 301",
        "F015_ID_PAIS": "169",
        "F015_ID_DEPTO": "05",
        "F015_ID_CIUDAD": "001",
        "F015_TELEFONO": "3001112233",
        "F015_EMAIL": "cliente.prueba@example.com",
        "F015_CELULAR": "3001112233",
    }


def test_fila_cliente(tercero):
    fila, recortada = fila_cliente(tercero, "20261019")
    assert list(fila) == list(CLIENTES_COLUMNS) and not recortada
    assert fila["F201_ID_TERCERO"] == "1017000001"
    assert fila["F201_DESCRIPCION_SUCURSAL"] == fila["F015_CONTACTO"] == "LAURA RESTREPO"
    fijos = ("F201_ID_SUCURSAL", "F201_ID_VENDEDOR", "F201_ID_COND_PAGO", "F201_ID_TIPO_CLI",
             "F201_PORC_MIN_MARGEN", "F201_PORC_MAX_MARGEN", "f201_id_cobrador")  # fmt: skip
    assert [fila[c] for c in fijos] == ["001", "W001", "03D", "C001", "1", "500", "W001"]
    # Clientes tiene 2 campos de dirección: el complemento pasa al segundo.
    assert (fila["F015_DIRECCION1"], fila["F015_DIRECCION2"]) == ("Calle 10 # 20-30", "Apto 301")
    assert (fila["F015_ID_PAIS"], fila["F015_ID_DEPTO"], fila["F015_ID_CIUDAD"]) == ("169", "05", "001")
    assert fila["F015_ID_BARRIO"] == ""
    assert fila["F015_TELEFONO"] == fila["f015_celular"] == "3001112233"
    assert fila["F201_FECHA_INGRESO"] == "20261019"


def test_direccion_2_y_3_no_caben_en_un_campo(tercero):
    tercero["F015_DIRECCION2"] = "Edificio Torre Empresarial Norte"
    tercero["F015_DIRECCION3"] = "Oficina 1201"
    fila, recortada = fila_cliente(tercero, "20261019")
    assert fila["F015_DIRECCION2"] == "Edificio Torre Empresarial Norte Oficina"
    assert recortada


def test_impuestos_por_bloques():
    filas = filas_impuestos(["111", "222"])
    assert [
        (f["F_TIPO_REG"], f["F_ID_TERCERO"], f["F_ID_CLASE"], f["F_ID_VALOR_TERCERO"]) for f in filas
    ] == [
        ("46", "111", "1", "1"),
        ("46", "222", "1", "1"),
        ("47", "111", "1", "0"),
        ("47", "222", "1", "0"),
        ("47", "111", "41", "1"),
        ("47", "222", "41", "1"),
    ]
    assert {f["F_ID_SUCURSAL"] for f in filas} == {"001"}


def test_entidad_dinamica_lleva_el_correo(tercero):
    assert fila_entidad(tercero) == {
        "f201_id_tercero": "1017000001",
        "f201_id_sucursal": "001",
        "f753_dato_texto": "cliente.prueba@example.com",
    }
