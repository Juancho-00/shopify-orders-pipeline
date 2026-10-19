"""
Fase 3 · Plantilla de clientes, hojas ``Clientes``, ``Imptos y Reten`` y
``Ent. Dinamica Cliente`` (definidas por TI el 2026-10-19).

Las tres se arman a partir de la fila ya calculada de la hoja ``Terceros``
(``terceros.fila_tercero``), así nombre, dirección, ciudad y teléfono salen idénticos en
las cuatro hojas.

``Clientes`` (tabla F201): el tercero como cliente, con valores fijos de e-commerce.
``Imptos y Reten``: cada cliente aparece 3 veces (es responsable de IVA, no se le retiene
    en la fuente y es autorretenedor). Las filas van por bloques, como en la plantilla de
    ejemplo: primero el registro ``46`` de todos los clientes, luego el ``47/1`` de todos y
    al final el ``47/41`` de todos.
``Ent. Dinamica Cliente``: el correo del cliente como dato adicional.
"""

from __future__ import annotations

from shopify_pipeline.erp.terceros import partir_texto

SUCURSAL = "001"

CLIENTES_COLUMNS: tuple[str, ...] = (
    "F201_ID_TERCERO",
    "F201_ID_SUCURSAL",
    "F201_DESCRIPCION_SUCURSAL",
    "F201_ID_VENDEDOR",
    "F201_ID_COND_PAGO",
    "F201_ID_TIPO_CLI",
    "F201_PORC_MIN_MARGEN",
    "F201_PORC_MAX_MARGEN",
    "F015_CONTACTO",
    "F015_DIRECCION1",
    "F015_DIRECCION2",
    "F015_ID_PAIS",
    "F015_ID_DEPTO",
    "F015_ID_CIUDAD",
    "F015_ID_BARRIO",
    "F015_TELEFONO",
    "F015_EMAIL",
    "F201_FECHA_INGRESO",
    "f201_id_cobrador",
    "f015_celular",
)

# Valores fijos de los clientes de e-commerce (R-32 / R-33).
FIJOS_CLIENTE: dict[str, str] = {
    "F201_ID_SUCURSAL": SUCURSAL,
    "F201_ID_VENDEDOR": "W001",
    "F201_ID_COND_PAGO": "03D",
    "F201_ID_TIPO_CLI": "C001",
    "F201_PORC_MIN_MARGEN": "1",
    "F201_PORC_MAX_MARGEN": "500",
    "f201_id_cobrador": "W001",
}

IMPUESTOS_COLUMNS: tuple[str, ...] = (
    "F_TIPO_REG",
    "F_ID_TERCERO",
    "F_ID_SUCURSAL",
    "F_ID_CLASE",
    "F_ID_VALOR_TERCERO",
)

# (F_TIPO_REG, F_ID_CLASE, F_ID_VALOR_TERCERO), en el orden de la plantilla.
CLASES_IMPUESTO: tuple[tuple[str, str, str], ...] = (
    ("46", "1", "1"),  # Responsable de IVA
    ("47", "1", "0"),  # No se le retiene en la fuente
    ("47", "41", "1"),  # Autorretenedor
)

ENTIDAD_COLUMNS: tuple[str, ...] = ("f201_id_tercero", "f201_id_sucursal", "f753_dato_texto")


def fila_cliente(tercero: dict[str, str], fecha_carga: str) -> tuple[dict[str, str], bool]:
    """
    Fila de la hoja ``Clientes`` a partir de la fila de ``Terceros``.

    ``Clientes`` tiene 2 campos de dirección (``Terceros`` tiene 3): el segundo lleva la
    continuación de la dirección y, si queda libre, el complemento. Devuelve
    ``(fila, recortada)``; ``recortada`` indica que algo de la dirección no cupo.
    """
    resto = " ".join(p for p in (tercero["F015_DIRECCION2"], tercero["F015_DIRECCION3"]) if p)
    trozos = partir_texto(resto)
    fila = {
        "F201_ID_TERCERO": tercero["F200_ID"],
        **FIJOS_CLIENTE,
        "F201_DESCRIPCION_SUCURSAL": tercero["F015_CONTACTO"],
        "F015_CONTACTO": tercero["F015_CONTACTO"],
        "F015_DIRECCION1": tercero["F015_DIRECCION1"],
        "F015_DIRECCION2": trozos[0] if trozos else "",
        "F015_ID_PAIS": tercero["F015_ID_PAIS"],
        "F015_ID_DEPTO": tercero["F015_ID_DEPTO"],
        "F015_ID_CIUDAD": tercero["F015_ID_CIUDAD"],
        "F015_ID_BARRIO": "",
        "F015_TELEFONO": tercero["F015_TELEFONO"],
        "F015_EMAIL": tercero["F015_EMAIL"],
        "F201_FECHA_INGRESO": fecha_carga,
        "f015_celular": tercero["F015_CELULAR"],
    }
    return {col: fila[col] for col in CLIENTES_COLUMNS}, len(trozos) > 1


def filas_impuestos(documentos: list[str]) -> list[dict[str, str]]:
    """3 filas por cliente, agrupadas por clase de impuesto (como la plantilla de ejemplo)."""
    return [
        {
            "F_TIPO_REG": tipo,
            "F_ID_TERCERO": documento,
            "F_ID_SUCURSAL": SUCURSAL,
            "F_ID_CLASE": clase,
            "F_ID_VALOR_TERCERO": valor,
        }
        for tipo, clase, valor in CLASES_IMPUESTO
        for documento in documentos
    ]


def fila_entidad(tercero: dict[str, str]) -> dict[str, str]:
    return {
        "f201_id_tercero": tercero["F200_ID"],
        "f201_id_sucursal": SUCURSAL,
        "f753_dato_texto": tercero["F015_EMAIL"],
    }
