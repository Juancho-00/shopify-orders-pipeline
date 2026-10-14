"""
Funciones de limpieza de datos de clientes colombianos.

Todas son puras (sin llamadas a la API), así que se prueban fácilmente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Colombia no tiene horario de verano: UTC-5 fijo. Evita depender de la base de
# zonas horarias, que en Windows requiere instalar el paquete tzdata.
BOGOTA = timezone(timedelta(hours=-5), "America/Bogota")

TWO_PLACES = Decimal("0.01")

# Partículas que forman parte del apellido: "De la Torre", "Del Valle", "San Martín".
_PARTICULAS = {"de", "del", "la", "las", "los", "y", "san", "santa", "da", "das", "do", "dos", "van", "von"}

_TIPO_DOC_PREFIJO = re.compile(
    r"^\s*(NIT|C\.?\s?C\.?|C\.?\s?E\.?|CEDULA|CÉDULA|PASAPORTE|PP)\b[\s:.#\-]*",
    re.IGNORECASE,
)

# Pesos oficiales de la DIAN para el dígito de verificación, del dígito menos significativo al más.
_PESOS_DV = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)


# --------------------------------------------------------------------- texto
def clean_text(value: object) -> str:
    """Convierte a texto, quita saltos de línea y espacios repetidos. ``None`` → ``""``."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def split_nombres(first_name: object) -> tuple[str, str]:
    """``"Juan Pablo"`` → ``("Juan", "Pablo")``. El resto de palabras va al segundo nombre."""
    tokens = clean_text(first_name).split(" ")
    tokens = [t for t in tokens if t]
    if not tokens:
        return "", ""
    return tokens[0], " ".join(tokens[1:])


def split_apellidos(last_name: object) -> tuple[str, str]:
    """
    ``"Lozano Gutierrez"`` → ``("Lozano", "Gutierrez")``.
    ``"De la Torre Gómez"`` → ``("De la Torre", "Gómez")`` (respeta partículas).
    """
    tokens = [t for t in clean_text(last_name).split(" ") if t]
    grupos: list[str] = []
    pendiente: list[str] = []
    for token in tokens:
        pendiente.append(token)
        if token.lower() not in _PARTICULAS:
            grupos.append(" ".join(pendiente))
            pendiente = []
    if pendiente:  # Partículas al final, sin palabra que las siga.
        if grupos:
            grupos[-1] = f"{grupos[-1]} {' '.join(pendiente)}"
        else:
            grupos.append(" ".join(pendiente))
    if not grupos:
        return "", ""
    return grupos[0], " ".join(grupos[1:])


# ---------------------------------------------------------------- documento
@dataclass(frozen=True)
class Documento:
    tipo: str  # "CC", "NIT", "CE", "PP" o "" si no hay documento
    numero: str  # solo dígitos (o alfanumérico para pasaporte)
    dv: str  # dígito de verificación (solo NIT)
    alertas: tuple[str, ...] = ()


def calcular_dv_nit(numero: str) -> str:
    """Dígito de verificación del NIT según el algoritmo de la DIAN."""
    digitos = [int(d) for d in reversed(numero)]
    if len(digitos) > len(_PESOS_DV):
        raise ValueError("NIT demasiado largo para calcular el DV.")
    residuo = sum(d * p for d, p in zip(digitos, _PESOS_DV, strict=False)) % 11
    return str(residuo if residuo in (0, 1) else 11 - residuo)


def parse_documento(raw: object) -> Documento:
    """
    Interpreta el documento escrito por el cliente en el campo ``company``.

    Acepta formatos como ``1152469156``, ``1.152.469.156``, ``CC 1152469156``,
    ``900123456-7`` o ``NIT 900.123.456``.

    Tipo de documento:
      * Prefijo explícito (CC, NIT, CE, PP) → se respeta.
      * Con guion (``900123456-7``) → NIT con dígito de verificación.
      * 9 dígitos que empiezan por 8 o 9 → NIT de empresa (rango asignado por la DIAN).
      * Cualquier otro número → CC.

    Para un NIT sin DV, el DV se calcula. Si el cliente lo escribió y no coincide, se
    agrega la alerta ``DV_NIT_INVALIDO``.

    REGLA PROVISIONAL: aún no está definido cómo identificar un NIT. Mientras tanto, un
    NIT deducido solo por la regla de 9 dígitos (sin prefijo ni guion) se marca con
    ``NIT_POR_VERIFICAR`` para revisarlo en el log de alertas.
    """
    text = clean_text(raw).upper()
    if not text:
        return Documento("", "", "", ("SIN_DOCUMENTO",))

    tipo = ""
    match = _TIPO_DOC_PREFIJO.match(text)
    if match:
        prefijo = re.sub(r"[^A-ZÉ]", "", match.group(1))
        tipo = {"CC": "CC", "CEDULA": "CC", "CÉDULA": "CC", "NIT": "NIT", "CE": "CE"}.get(prefijo, "PP")
        text = text[match.end() :]

    if tipo == "PP":
        numero = re.sub(r"[^A-Z0-9]", "", text)
        return Documento("PP", numero, "", () if numero else ("DOCUMENTO_INVALIDO",))

    dv_escrito = ""
    if "-" in text:
        base, _, resto = text.partition("-")
        dv_escrito = re.sub(r"\D", "", resto)[:1]
        text = base
        tipo = tipo or "NIT"
    numero = re.sub(r"\D", "", text)

    if not 5 <= len(numero) <= 11:
        return Documento(tipo or "CC", numero, "", ("DOCUMENTO_INVALIDO",))

    nit_inferido = False
    if not tipo:
        nit_inferido = len(numero) == 9 and numero[0] in "89"
        tipo = "NIT" if nit_inferido else "CC"

    if tipo != "NIT":
        return Documento(tipo, numero, "")

    dv = calcular_dv_nit(numero)
    alertas: list[str] = []
    if nit_inferido:
        alertas.append("NIT_POR_VERIFICAR")
    if dv_escrito and dv_escrito != dv:
        alertas.append("DV_NIT_INVALIDO")
    return Documento("NIT", numero, dv_escrito or dv, tuple(alertas))


# ------------------------------------------------------------------ contacto
def normalize_phone(raw: object) -> str:
    """``"+57 323 501 6059"`` → ``"3235016059"``. Quita el indicativo de Colombia."""
    digits = re.sub(r"\D", "", clean_text(raw))
    if len(digits) == 12 and digits.startswith("57"):
        digits = digits[2:]
    return digits


# ------------------------------------------------------------ números/fechas
def to_decimal(value: object) -> Decimal:
    """Convierte montos de Shopify (texto) a Decimal con 2 decimales. Vacío → 0."""
    if value in (None, ""):
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"Monto inválido: {value!r}") from exc


def to_bogota(value: object) -> str:
    """ISO 8601 de Shopify → ``"YYYY-MM-DD HH:MM:SS"`` en hora de Colombia. Vacío → ``""``."""
    text = clean_text(value)
    if not text:
        return ""
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(BOGOTA).strftime("%Y-%m-%d %H:%M:%S")
