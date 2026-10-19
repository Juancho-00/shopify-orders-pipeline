"""Catálogos Siesa: bodegas (R-09) y ciudades (R-11)."""

from __future__ import annotations

import pytest

from shopify_pipeline.transform.catalogos import codigo_bodega, codigo_ciudad, normalizar, partes_ciudad


@pytest.mark.parametrize(
    ("nombre", "codigo"),
    [("D'Luchi PT Guarne", "LCD01"), ("D’Luchi PT Guarne", "LCD01"), ("  d'luchi pt guarne ", "LCD01"),
     ("Bodega Inventada", ""), ("", "")],
)  # fmt: skip
def test_codigo_bodega(nombre, codigo):
    assert codigo_bodega(nombre) == codigo


@pytest.mark.parametrize(
    ("ciudad", "depto", "provincia", "codigo"),
    [
        ("Medellin", "Antioquia", "ANT", "16905001"),
        ("MEDELLÍN", "", "ANT", "16905001"),
        ("Bogota", "Bogotá D.C.", "DC", "16911001"),
        ("Bogotá D.C.", "", "", "16911001"),
        ("Cartagena", "Bolívar", "BOL", "16913001"),
        ("La Union", "Antioquia", "ANT", "16905400"),  # nombre repetido: se decide por depto
        ("Itagui", "Antioquia", "ANT", "16905360"),
        ("Medelin", "Antioquia", "ANT", ""),  # error de digitación: no se adivina
        ("", "Antioquia", "ANT", ""),
        ("Envigado", "", "", "16905266"),  # sin departamento: nombre único en el país
        ("La Union", "", "", ""),  # sin departamento y repetido: no se adivina
    ],
)
def test_codigo_ciudad(ciudad, depto, provincia, codigo):
    assert codigo_ciudad(ciudad, depto, provincia) == codigo


def test_partes_ciudad():
    assert partes_ciudad("16905001") == ("169", "05", "001")


def test_normalizar():
    assert normalizar("  Itagüí – D’Luchi ") == "itagui dluchi"
