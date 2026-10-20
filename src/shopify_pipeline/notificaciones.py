"""
Aviso por correo del resultado de la corrida diaria (Gmail / Google Workspace).

QUÉ HACE
    Al final de ``scripts/ejecutar_pipeline.ps1`` se ejecuta ``shopify-pipeline notificar``.
    Lee la última línea de ``data/logs/ejecuciones.csv`` (y, si hubo plantillas, su log y sus
    archivos) y envía un correo:

    * Si falló: qué paso falló, qué significa el código y qué hacer.
    * Si salió bien: cuántos clientes y pedidos quedaron listos para validar y subir, cuántos
      pedidos quedaron por fuera y por qué.

    Con ``NOTIFICAR_SOLO_FALLOS=true`` solo se envía cuando algo sale mal.

PRIVACIDAD
    El correo nunca lleva datos de clientes ni adjunta las plantillas: solo conteos, códigos
    y rutas de archivos. Los datos personales se quedan en la carpeta de Drive.

CONFIGURACIÓN (.env)
    NOTIFICAR_A=ti@empresa.com,otra@empresa.com   # destinatarios (vacío = no se envía nada)
    SMTP_USUARIO=avisos@empresa.com               # cuenta de Google que envía
    SMTP_CLAVE=xxxx xxxx xxxx xxxx                # contraseña de aplicación de Google (16 letras)
    SMTP_HOST=smtp.gmail.com  SMTP_PUERTO=587     # opcionales, ya vienen así por defecto

    La contraseña de aplicación se crea en https://myaccount.google.com/apppasswords y
    necesita la verificación en dos pasos activa en esa cuenta. No es la contraseña normal.
"""

from __future__ import annotations

import csv
import logging
import os
import smtplib
import ssl
from collections import Counter
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

# Qué hacer ante cada resultado (resumen de docs/ejecucion_programada.md).
QUE_HACER: dict[str, str] = {
    "OK": "Validar las plantillas y subirlas a Siesa: primero clientes, luego pedidos.",
    "ERROR_DATOS": "Hay plantillas, pero algunos pedidos quedaron por fuera: ver el log de plantillas.",
    "CONTEO_NO_CUADRA": "Hay plantillas. Shopify cambió algún pedido durante la extracción; "
    "la próxima corrida repite el periodo. Si se repite varios días, revisar.",
    "ERROR_TEMPORAL": "No hay plantillas. Revisar internet, Shopify, que ningún archivo de data\\ esté "
    "abierto en Excel y que Drive esté sincronizado; luego correr scripts\\ejecutar_pipeline.ps1 a mano.",
    "ERROR_CONFIGURACION": "No hay plantillas. Credenciales vencidas, permiso faltante o .env mal: "
    "revisar la bitácora. No se arregla esperando.",
    "ERROR_INESPERADO": "No hay plantillas. Posible bug: revisar la traza en la bitácora del día.",
}
RESULTADOS_CON_PLANTILLAS = frozenset({"OK", "ERROR_DATOS", "CONTEO_NO_CUADRA"})


@dataclass(frozen=True)
class ConfigCorreo:
    destinatarios: tuple[str, ...]
    usuario: str
    clave: str = field(repr=False)
    host: str = "smtp.gmail.com"
    puerto: int = 587
    solo_fallos: bool = False

    @classmethod
    def from_env(cls) -> ConfigCorreo | None:
        """``None`` si falta configuración: los avisos quedan desactivados, sin error."""
        destinatarios = tuple(d.strip() for d in os.environ.get("NOTIFICAR_A", "").split(",") if d.strip())
        usuario = os.environ.get("SMTP_USUARIO", "").strip()
        clave = os.environ.get("SMTP_CLAVE", "").replace(" ", "")
        if not (destinatarios and usuario and clave):
            return None
        return cls(
            destinatarios=destinatarios,
            usuario=usuario,
            clave=clave,
            host=os.environ.get("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com",
            puerto=int(os.environ.get("SMTP_PUERTO", "587") or 587),
            solo_fallos=os.environ.get("NOTIFICAR_SOLO_FALLOS", "").strip().lower()
            in {"1", "true", "si", "sí"},
        )


def ultima_ejecucion(log_dir: Path) -> dict[str, str] | None:
    historial = log_dir / "ejecuciones.csv"
    if not historial.exists():
        return None
    with historial.open(encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.DictReader(fh))
    return filas[-1] if filas else None


def _filas_hoja(path: Path, hoja: str) -> int | None:
    """Cuántas filas de datos tiene una hoja (sin leer su contenido)."""
    if not path.exists():
        return None
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True)
    try:
        ws = wb[hoja]
        # No se confía en la dimensión declarada por el archivo: los escritos en modo
        # streaming (o re-guardados por otras herramientas) pueden no traerla. Contar las
        # filas recorriéndolas sigue siendo de memoria constante en modo read_only.
        ws.reset_dimensions()
        return sum(1 for _ in ws.iter_rows(min_row=2, values_only=True))
    finally:
        wb.close()


def _eventos(path: Path) -> tuple[Counter[str], Counter[str]]:
    """(exclusiones, alertas) por código, del log de plantillas."""
    excluidos: Counter[str] = Counter()
    alertas: Counter[str] = Counter()
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for e in csv.DictReader(fh):
                (excluidos if e.get("tipo") == "EXCLUIDO" else alertas)[e.get("codigo", "")] += 1
    return excluidos, alertas


def _conteo(c: Counter[str]) -> str:
    return "\n".join(f"  - {codigo}: {n}" for codigo, n in c.most_common()) or "  - ninguno"


def armar_correo(
    ejecucion: dict[str, str], run_id: str = "", data_dir: Path = Path("data")
) -> tuple[str, str]:
    """Devuelve ``(asunto, cuerpo)``. Solo conteos y códigos: ningún dato de clientes."""
    resultado = ejecucion.get("resultado", "DESCONOCIDO")
    fecha = ejecucion.get("fecha", "")
    lineas = [
        f"Corrida del {fecha}",
        "",
        f"Resultado general: {resultado} (código {ejecucion.get('codigo', '?')})",
        f"  1. Extracción de Shopify: {ejecucion.get('extraccion', '?')} "
        f"({ejecucion.get('intentos_extraccion', '?')} intento(s))",
        f"  2. Plantillas de Siesa:   {ejecucion.get('plantillas', '?')}",
        "",
        f"Qué hacer: {QUE_HACER.get(resultado, 'Revisar la bitácora del día.')}",
    ]
    asunto = f"[Shopify → Siesa] {fecha[:10]} · {resultado}"

    if run_id and resultado in RESULTADOS_CON_PLANTILLAS:
        cargas = data_dir / "siesa" / "cargas"
        clientes = _filas_hoja(cargas / f"terceros_{run_id}.xlsx", "Terceros")
        pedidos = _filas_hoja(cargas / f"pedidos_{run_id}.xlsx", "Pedidos")
        excluidos, alertas = _eventos(data_dir / "logs" / f"plantillas_{run_id}.csv")
        vending = excluidos.pop("BODEGA_NO_SE_CARGA", 0)
        if pedidos is not None:
            asunto = f"[Shopify → Siesa] {fecha[:10]} · {pedidos} pedidos listos para subir"
            if excluidos:
                asunto += f" · {sum(excluidos.values())} por revisar"
        lineas += [
            "",
            "Listo para validar y subir (data\\siesa\\cargas\\):",
            f"  1. terceros_{run_id}.xlsx  → {clientes if clientes is not None else '?'} clientes",
            f"  2. pedidos_{run_id}.xlsx   → {pedidos if pedidos is not None else '?'} pedidos",
            "",
            "Pedidos que NO van en las plantillas (corregir y cargar aparte):",
            _conteo(excluidos),
            f"Pedidos de vending (no se cargan a Siesa): {vending}",
            "",
            "Alertas (el pedido sí va, pero conviene revisar el dato):",
            _conteo(alertas),
            "",
            f"Detalle por pedido: data\\logs\\plantillas_{run_id}.csv",
        ]
    lineas += [
        "",
        "Bitácora del día: data\\logs\\shopify_pipeline_AAAAMMDD.log",
        "Historial: data\\logs\\ejecuciones.csv",
        "",
        "— Aviso automático del pipeline Shopify → Siesa. Este correo no lleva datos de clientes.",
    ]
    return asunto, "\n".join(lineas)


def enviar(config: ConfigCorreo, asunto: str, cuerpo: str) -> None:
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = config.usuario
    mensaje["To"] = ", ".join(config.destinatarios)
    mensaje.set_content(cuerpo)
    with smtplib.SMTP(config.host, config.puerto, timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(config.usuario, config.clave)
        smtp.send_message(mensaje)


def notificar(log_dir: Path, run_id: str = "", data_dir: Path = Path("data")) -> bool:
    """
    Envía el aviso de la última corrida. Devuelve True si se envió.

    Nunca lanza excepciones: un problema con el correo no debe convertir en fallida una
    corrida que salió bien. Queda anotado en la bitácora.
    """
    config = ConfigCorreo.from_env()
    if config is None:
        logger.info("Avisos por correo desactivados (faltan NOTIFICAR_A, SMTP_USUARIO o SMTP_CLAVE en .env).")
        return False
    ejecucion = ultima_ejecucion(log_dir)
    if ejecucion is None:
        logger.warning("No hay ejecuciones en %s: no se envía aviso.", log_dir / "ejecuciones.csv")
        return False
    if config.solo_fallos and ejecucion.get("resultado") == "OK":
        logger.info("Corrida OK y NOTIFICAR_SOLO_FALLOS activo: no se envía aviso.")
        return False
    asunto, cuerpo = armar_correo(ejecucion, run_id, data_dir)
    try:
        enviar(config, asunto, cuerpo)
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail rechazó el usuario o la clave (SMTP_USUARIO / SMTP_CLAVE). Use una contraseña de "
            "aplicación de Google, no la contraseña normal."
        )
        return False
    except (OSError, smtplib.SMTPException) as exc:
        logger.error("No se pudo enviar el aviso por correo: %s", exc)
        return False
    logger.info("Aviso enviado a %s: %s", ", ".join(config.destinatarios), asunto)
    return True
