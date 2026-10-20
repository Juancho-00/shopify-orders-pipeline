"""
Fase 3 · Plantilla de clientes, hoja ``Terceros`` (tabla F200 + contacto F015 de Siesa).

QUÉ HACE
    Convierte un pedido del reporte de la fase 1 (``pedidos_siesa_<run_id>.csv``) en la
    fila del tercero para la plantilla de Siesa. La estructura completa de la plantilla
    está en ``docs/plantillas_siesa.md``.

REGLAS (definidas el 2026-10-19)
    * ``F200_ID`` = ``F200_NIT`` = número de documento (sin DV).
    * ``F200_ID_TIPO_IDENT``: ``C`` cédula, ``N`` NIT.
    * ``F200_IND_TIPO_TERCERO``: siempre ``1``.
    * NIT: ``F200_RAZON_SOCIAL`` = nombre de la empresa; cédula: vacío.
    * NIT: la razón social sale del campo ``company`` de Shopify (columna ``razon_social`` del
      reporte); apellidos y nombres van vacíos.
    * ``F015_CONTACTO``: nombre completo en orden APELLIDOS NOMBRES, o la razón social si es NIT.
    * Email y teléfono son obligatorios: se necesitan para la facturación electrónica.
    * Direcciones 1, 2 y 3: máximo 40 caracteres cada una. Si la dirección no cabe en la
      1, sigue en la 2 (cortando entre palabras); el complemento va en la 3.
    * ``F015_ID_PAIS`` siempre ``169``; departamento (2 dígitos) y ciudad (3 dígitos) salen
      de ``codigo_ciudad_siesa``. ``F015_ID_BARRIO`` vacío.
    * ``F015_TELEFONO`` = ``F015_CELULAR`` = celular SIN el indicativo ``57`` / ``+57``.
    * ``F200_FECHA_NACIMIENTO``: Shopify no la tiene; va la fecha de la carga en formato
      ``AAAAMMDD`` (``20261019``), como texto, igual que en la plantilla de ejemplo.

Si falta un dato obligatorio, el tercero no se genera (R-34) y se devuelve qué falta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from shopify_pipeline.transform.catalogos import partes_ciudad
from shopify_pipeline.transform.normalize import normalize_phone

TERCEROS_COLUMNS: tuple[str, ...] = (
    "F200_ID",
    "F200_NIT",
    "F200_ID_TIPO_IDENT",
    "F200_IND_TIPO_TERCERO",
    "F200_RAZON_SOCIAL",
    "F200_APELLIDO1",
    "F200_APELLIDO2",
    "F200_NOMBRES",
    "F015_CONTACTO",
    "F015_DIRECCION1",
    "F015_DIRECCION2",
    "F015_DIRECCION3",
    "F015_ID_PAIS",
    "F015_ID_DEPTO",
    "F015_ID_CIUDAD",
    "F015_ID_BARRIO",
    "F015_TELEFONO",
    "F015_EMAIL",
    "F200_FECHA_NACIMIENTO",
    "F015_CELULAR",
)

LARGO_DIRECCION = 40
LARGO_MINIMO_TELEFONO = 7  # Fijo de 7 dígitos o celular de 10.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
IND_TIPO_TERCERO = "1"
ID_PAIS = "169"  # Colombia
# Columnas que la plantilla de ejemplo guarda como número; las demás van como texto.
COLUMNAS_NUMERICAS = frozenset({"F200_ID", "F200_NIT"})


@dataclass(frozen=True)
class Tercero:
    fila: dict[str, str]
    faltantes: tuple[str, ...] = ()  # Datos obligatorios ausentes: el tercero no se carga.
    alertas: tuple[str, ...] = field(default=())

    @property
    def cargable(self) -> bool:
        return not self.faltantes


def _mayus(*partes: str | None) -> str:
    return " ".join(p.strip() for p in partes if p and p.strip()).upper()


def partir_texto(texto: str, largo: int = LARGO_DIRECCION) -> list[str]:
    """
    Corta un texto en trozos de ``largo`` caracteres sin partir palabras.

    ``"Carrera 43A # 1 Sur - 100 Edificio Torre Empresarial"`` →
    ``["Carrera 43A # 1 Sur - 100 Edificio Torre", "Empresarial"]``.
    Una palabra más larga que ``largo`` se corta a la fuerza.
    """
    trozos: list[str] = []
    actual = ""
    for palabra in texto.split():
        while len(palabra) > largo:
            if actual:
                trozos.append(actual)
                actual = ""
            trozos.append(palabra[:largo])
            palabra = palabra[largo:]
        if not actual:
            actual = palabra
        elif len(actual) + 1 + len(palabra) <= largo:
            actual = f"{actual} {palabra}"
        else:
            trozos.append(actual)
            actual = palabra
    if actual:
        trozos.append(actual)
    return trozos


def repartir_direccion(direccion: str, complemento: str) -> tuple[str, str, str, bool]:
    """
    Reparte la dirección en los 3 campos de 40 caracteres de Siesa.

    Dirección → campos 1 y 2; complemento → campo 3. Si el complemento no cabe en el 3 y
    el 2 quedó libre, el complemento pasa a los campos 2 y 3. Devuelve
    ``(dir1, dir2, dir3, truncada)``; ``truncada`` indica que algo no cupo.
    """
    dir_ = partir_texto(direccion)
    comp = partir_texto(complemento)
    if len(dir_) <= 1 and len(comp) > 1:
        campos = [dir_[0] if dir_ else "", *comp[:2]]
        truncada = len(comp) > 2
    else:
        campos = [*dir_[:2], *([""] * (2 - len(dir_[:2]))), comp[0] if comp else ""]
        truncada = len(dir_) > 2 or len(comp) > 1
    return campos[0], campos[1], campos[2], truncada


def fila_tercero(pedido: dict[str, str], fecha_carga: str) -> Tercero:
    """
    Fila de la hoja ``Terceros`` a partir de una fila del reporte de la fase 1.

    ``fecha_carga`` va en ``AAAAMMDD``: se usa como fecha de nacimiento.
    """
    tipo = (pedido.get("tipo_documento") or "").strip()
    documento = (pedido.get("numero_documento") or "").strip()
    nombres = _mayus(pedido.get("primer_nombre"), pedido.get("segundo_nombre"))
    apellido1 = _mayus(pedido.get("primer_apellido"))
    apellido2 = _mayus(pedido.get("segundo_apellido"))
    completo = _mayus(apellido1, apellido2, nombres)  # Orden de Siesa: APELLIDOS NOMBRES.

    es_nit = tipo == "N"
    # Reportes anteriores a la columna razon_social: se usa el nombre de facturación.
    razon_social = (
        (_mayus(pedido.get("razon_social")) or _mayus(nombres, apellido1, apellido2)) if es_nit else ""
    )
    contacto = razon_social if es_nit else completo
    dir1, dir2, dir3, truncada = repartir_direccion(
        pedido.get("direccion") or "", pedido.get("direccion_complemento") or ""
    )
    _, depto, ciudad = partes_ciudad((pedido.get("codigo_ciudad_siesa") or "").strip())
    telefono = normalize_phone(pedido.get("telefono") or "")  # Sin 57 / +57.
    email = (pedido.get("email") or "").strip()

    faltantes = [
        nombre
        for nombre, valor in (
            ("numero_documento", documento),
            ("tipo_documento", tipo),
            ("nombre" if not es_nit else "razon_social", contacto),
            ("direccion", dir1),
            ("codigo_ciudad_siesa", ciudad),
            ("email", email if _EMAIL.fullmatch(email) else ""),
            ("telefono", telefono if len(telefono) >= LARGO_MINIMO_TELEFONO else ""),
        )
        if not valor
    ]
    if not es_nit and not apellido1:
        faltantes.append("primer_apellido")
    if not es_nit and not nombres:
        faltantes.append("primer_nombre")
    alertas = ["DIRECCION_TRUNCADA"] if truncada else []

    fila = {
        "F200_ID": documento,
        "F200_NIT": documento,
        "F200_ID_TIPO_IDENT": tipo,
        "F200_IND_TIPO_TERCERO": IND_TIPO_TERCERO,
        "F200_RAZON_SOCIAL": razon_social,
        "F200_APELLIDO1": "" if es_nit else apellido1,
        "F200_APELLIDO2": "" if es_nit else apellido2,
        "F200_NOMBRES": "" if es_nit else nombres,
        "F015_CONTACTO": contacto,
        "F015_DIRECCION1": dir1,
        "F015_DIRECCION2": dir2,
        "F015_DIRECCION3": dir3,
        "F015_ID_PAIS": ID_PAIS,
        "F015_ID_DEPTO": depto,
        "F015_ID_CIUDAD": ciudad,
        "F015_ID_BARRIO": "",
        "F015_TELEFONO": telefono,
        "F015_EMAIL": email,
        "F200_FECHA_NACIMIENTO": fecha_carga,
        "F015_CELULAR": telefono,
    }
    return Tercero(fila, tuple(faltantes), tuple(alertas))
