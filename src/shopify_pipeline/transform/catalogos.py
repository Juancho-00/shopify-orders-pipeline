"""
Catálogos de equivalencias con Siesa: bodegas (R-09) y ciudades (R-11).

QUÉ HACE
    Lee las tablas de ``shopify_pipeline/catalogos/`` y responde dos preguntas:

    * ``codigo_bodega("D'Luchi PT Guarne")`` → ``"LCD01"``
    * ``tipo_docto_bodega("LCD01")`` → ``"CPW"`` (tipo de documento del pedido en Siesa)
    * ``codigo_ciudad("Medellin", "Antioquia", "ANT")`` → ``"16905001"``

CÓMO COMPARA LOS TEXTOS
    Los nombres que escribe el cliente (o que tiene Shopify) no coinciden letra a letra con
    los de Siesa: "Medellin" vs "Medellín", "Bogota" vs "Bogotá, D.C.". Antes de comparar,
    ambos lados se *normalizan*: minúsculas, sin tildes, sin signos y con un solo espacio.

CIUDADES
    El código Siesa es ``169`` (Colombia) + 2 dígitos de departamento + 3 de ciudad (el
    código DANE). Se busca primero el departamento (por el código de provincia de
    Shopify o por su nombre) y luego la ciudad DENTRO de ese departamento, porque hay 63
    nombres de municipio repetidos en el país (p. ej. "La Unión" existe en 5 departamentos).
"""

from __future__ import annotations

import csv
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CATALOGOS_DIR = Path(__file__).resolve().parent.parent / "catalogos"
PAIS_COLOMBIA = "169"

# Código de provincia de Shopify (ISO 3166-2:CO) → código DANE del departamento.
PROVINCIA_A_DEPTO: dict[str, str] = {
    "AMA": "91", "ANT": "05", "ARA": "81", "ATL": "08", "BOL": "13", "BOY": "15",
    "CAL": "17", "CAQ": "18", "CAS": "85", "CAU": "19", "CES": "20", "CHO": "27",
    "COR": "23", "CUN": "25", "DC": "11", "GUA": "94", "GUV": "95", "HUI": "41",
    "LAG": "44", "MAG": "47", "MET": "50", "NAR": "52", "NSA": "54", "PUT": "86",
    "QUI": "63", "RIS": "66", "SAN": "68", "SAP": "88", "SUC": "70", "TOL": "73",
    "VAC": "76", "VAU": "97", "VID": "99",
}  # fmt: skip

# Palabras que sobran al comparar ciudades ("Bogotá, D.C.", "Cartagena de Indias").
_SOBRANTES = re.compile(r"\b(d c|dc|distrito capital|de indias)\b")


def normalizar(texto: object) -> str:
    """``"  Bogotá, D.C. "`` → ``"bogota d c"``. Minúsculas, sin tildes ni signos."""
    t = re.sub(r"['’‘`´]", "", str(texto or ""))  # D'Luchi = D’Luchi = DLuchi
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return " ".join(t.split())


def _dir() -> Path:
    return Path(os.environ.get("SIESA_CATALOGOS_DIR") or CATALOGOS_DIR)


def _leer_csv(nombre: str) -> list[dict[str, str]]:
    with (_dir() / nombre).open(encoding="utf-8-sig", newline="") as fh:
        return [{k: (v or "").strip() for k, v in fila.items()} for fila in csv.DictReader(fh)]


# ------------------------------------------------------------------- bodegas
@lru_cache(maxsize=4)
def _bodegas(_dir_key: str) -> dict[str, str]:
    return {normalizar(f["bodega_shopify"]): f["codigo_siesa"] for f in _leer_csv("bodegas_siesa.csv")}


def codigo_bodega(nombre_shopify: str) -> str:
    """Código de bodega Siesa para una ubicación de Shopify. ``""`` si no hay equivalencia."""
    return _bodegas(str(_dir())).get(normalizar(nombre_shopify), "")


@lru_cache(maxsize=4)
def _tipos_docto(_dir_key: str) -> dict[str, str]:
    return {
        f["codigo_siesa"].upper(): f.get("tipo_docto_siesa", "").upper()
        for f in _leer_csv("bodegas_siesa.csv")
    }


NO_CARGA = "NO_CARGA"  # Bodegas cuyos pedidos no se cargan a Siesa (vending).


def tipo_docto_bodega(codigo_siesa: str) -> str:
    """
    Tipo de documento del pedido en Siesa según la bodega de salida: ``LCD01`` → ``CPW``,
    tiendas ``LCM..`` → ``CPT``, Melonn ``LEC..`` → ``CPM``. ``NO_CARGA`` para las bodegas
    cuyos pedidos no van a Siesa (vending) y ``""`` si la bodega no tiene tipo configurado.
    """
    return _tipos_docto(str(_dir())).get(codigo_siesa.strip().upper(), "")


def bodega_no_se_carga(codigo_siesa: str) -> bool:
    """True para las bodegas cuyos pedidos no se cargan a Siesa (hoy, las 4 de vending)."""
    return tipo_docto_bodega(codigo_siesa) == NO_CARGA


# ------------------------------------------------------------------- ciudades
@dataclass(frozen=True)
class _Ciudades:
    deptos_por_nombre: dict[str, str]  # nombre normalizado → "05"
    ciudades: dict[str, dict[str, str]]  # "05" → {nombre normalizado → "16905001"}


@lru_cache(maxsize=4)
def _ciudades(_dir_key: str) -> _Ciudades:
    deptos: dict[str, str] = {}
    ciudades: dict[str, dict[str, str]] = {}
    for fila in _leer_csv("ciudades_siesa.csv"):
        codigo, nombre = fila["codigo"], fila["descripcion"]
        if len(codigo) == 5:
            deptos[normalizar(nombre)] = codigo[3:5]
        elif len(codigo) == 8:
            ciudades.setdefault(codigo[3:5], {})[normalizar(nombre)] = codigo
    return _Ciudades(deptos, ciudades)


def _depto(departamento: str, provincia_code: str) -> str:
    cat = _ciudades(str(_dir()))
    codigo = PROVINCIA_A_DEPTO.get(provincia_code.strip().upper(), "")
    if codigo:
        return codigo
    nombre = _SOBRANTES.sub("", normalizar(departamento)).strip()
    if nombre in cat.deptos_por_nombre:
        return cat.deptos_por_nombre[nombre]
    candidatos = {c for n, c in cat.deptos_por_nombre.items() if n.startswith(nombre) or nombre.startswith(n)}
    return candidatos.pop() if nombre and len(candidatos) == 1 else ""


def codigo_ciudad(ciudad: str, departamento: str = "", provincia_code: str = "") -> str:
    """
    Código Siesa de 8 dígitos (``16905001``) o ``""`` si no se puede determinar sin dudas.

    Busca la ciudad dentro de su departamento: primero el nombre exacto (normalizado);
    luego, si un solo municipio del departamento empieza igual, ese. Sin departamento, solo
    acepta un nombre exacto que no se repita en ningún otro departamento.
    """
    depto = _depto(departamento, provincia_code)
    if not depto:
        return _ciudad_unica(ciudad)
    del_depto = _ciudades(str(_dir())).ciudades.get(depto, {})
    if depto == "11":  # Bogotá D.C. tiene un solo municipio.
        return next(iter(del_depto.values()), "")
    nombre = _SOBRANTES.sub("", normalizar(ciudad)).strip()
    if not nombre:
        return ""
    limpios = {_SOBRANTES.sub("", n).strip(): c for n, c in del_depto.items()}
    if nombre in limpios:
        return limpios[nombre]
    candidatos = [c for n, c in limpios.items() if n.startswith(nombre) or nombre.startswith(n)]
    return candidatos[0] if len(candidatos) == 1 else ""


def _ciudad_unica(ciudad: str) -> str:
    """Código de la ciudad si su nombre existe en un solo departamento del país."""
    nombre = _SOBRANTES.sub("", normalizar(ciudad)).strip()
    if not nombre:
        return ""
    codigos = [
        c
        for ciudades in _ciudades(str(_dir())).ciudades.values()
        for n, c in ciudades.items()
        if _SOBRANTES.sub("", n).strip() == nombre
    ]
    return codigos[0] if len(codigos) == 1 else ""


def partes_ciudad(codigo: str) -> tuple[str, str, str]:
    """``"16905001"`` → ``("169", "05", "001")``: país, departamento y ciudad para la plantilla."""
    if len(codigo) != 8:
        return "", "", ""
    return codigo[:3], codigo[3:5], codigo[5:]
