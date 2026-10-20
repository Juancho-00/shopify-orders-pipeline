"""Aviso por correo: se simula el servidor de Gmail, nunca se envía un correo real."""

from __future__ import annotations

import csv
import smtplib
from datetime import date
from typing import ClassVar

import pytest

from shopify_pipeline import cli
from shopify_pipeline.erp.run import generar_plantillas
from shopify_pipeline.notificaciones import ConfigCorreo, armar_correo, notificar
from tests.test_erp_run import _fila, _reporte

COLUMNAS = ["fecha", "codigo", "resultado", "extraccion", "intentos_extraccion", "plantillas",
            "intentos_plantillas", "duracion_seg"]  # fmt: skip


def _historial(log_dir, codigo, resultado, extraccion, plantillas):
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "ejecuciones.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNAS)
        w.writerow(["2026-10-20 06:30:00", codigo, resultado, extraccion, 1, plantillas, 1, 12.5])


class SMTPFalso:
    """Reemplaza a smtplib.SMTP: guarda lo que se habría enviado."""

    enviados: ClassVar[list] = []
    falla_login = False

    def __init__(self, host, puerto, timeout):
        self.host, self.puerto = host, puerto

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        pass

    def login(self, usuario, clave):
        if SMTPFalso.falla_login:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
        self.usuario, self.clave = usuario, clave

    def send_message(self, mensaje):
        SMTPFalso.enviados.append((self.host, self.puerto, self.usuario, mensaje))


@pytest.fixture
def smtp(monkeypatch):
    SMTPFalso.enviados, SMTPFalso.falla_login = [], False
    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)
    monkeypatch.setenv("NOTIFICAR_A", "ti@example.com, otro@example.com")
    monkeypatch.setenv("SMTP_USUARIO", "avisos@example.com")
    monkeypatch.setenv("SMTP_CLAVE", "abcd efgh ijkl mnop")
    return SMTPFalso


def test_sin_configuracion_no_envia_nada(tmp_path):
    assert ConfigCorreo.from_env() is None
    _historial(tmp_path / "logs", 2, "ERROR_CONFIGURACION", "ERROR_CONFIGURACION", "NO_GENERADAS")
    assert notificar(tmp_path / "logs") is False


def test_config_quita_espacios_de_la_clave_y_lista_destinatarios(smtp):
    config = ConfigCorreo.from_env()
    assert config.destinatarios == ("ti@example.com", "otro@example.com")
    assert config.clave == "abcdefghijklmnop"
    assert (config.host, config.puerto) == ("smtp.gmail.com", 587)
    assert "abcd" not in repr(config)  # la clave nunca sale en los logs


def test_corrida_fallida(smtp, tmp_path):
    _historial(tmp_path / "logs", 2, "ERROR_CONFIGURACION", "ERROR_CONFIGURACION", "NO_GENERADAS")
    assert notificar(tmp_path / "logs") is True
    ((host, puerto, usuario, mensaje),) = smtp.enviados
    assert (host, puerto, usuario) == ("smtp.gmail.com", 587, "avisos@example.com")
    assert mensaje["Subject"] == "[Shopify → Siesa] 2026-10-20 · ERROR_CONFIGURACION"
    assert mensaje["To"] == "ti@example.com, otro@example.com"
    cuerpo = mensaje.get_content()
    assert "No hay plantillas" in cuerpo and "Credenciales" in cuerpo


def test_corrida_ok_resume_las_plantillas_sin_datos_de_clientes(smtp, tmp_path):
    reporte = _reporte(
        tmp_path / "pedidos_siesa_20261020T113000Z.csv",
        [
            _fila("2001", "70123456", "2026-10-19 09:00:00"),
            _fila("2002", "1017000001", "2026-10-19 10:00:00", email=""),  # no se carga
            _fila("2003", "1017000002", "2026-10-19 11:00:00", bodega_siesa="LCM55"),  # vending
        ],
    )
    generar_plantillas(reporte, tmp_path / "siesa" / "cargas", tmp_path / "logs", date(2026, 10, 20))
    _historial(tmp_path / "logs", 4, "ERROR_DATOS", "OK", "ERROR_DATOS")

    assert notificar(tmp_path / "logs", "20261020T113000Z", tmp_path) is True
    mensaje = smtp.enviados[0][3]
    assert mensaje["Subject"] == "[Shopify → Siesa] 2026-10-20 · 1 pedidos listos para subir · 1 por revisar"
    cuerpo = mensaje.get_content()
    assert "terceros_20261020T113000Z.xlsx  → 1 clientes" in cuerpo
    assert "TERCERO_INCOMPLETO: 1" in cuerpo
    assert "Pedidos de vending (no se cargan a Siesa): 1" in cuerpo
    # Nada de datos personales: ni documentos, ni nombres, ni correos de clientes.
    for dato in ("70123456", "1017000001", "Pérez", "ana@example.com"):
        assert dato not in cuerpo


def test_solo_fallos_no_envia_si_salio_bien(smtp, tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFICAR_SOLO_FALLOS", "true")
    _historial(tmp_path / "logs", 0, "OK", "OK", "OK")
    assert notificar(tmp_path / "logs") is False
    _historial(tmp_path / "logs", 1, "ERROR_TEMPORAL", "ERROR_TEMPORAL", "NO_GENERADAS")
    assert notificar(tmp_path / "logs") is True


def test_clave_rechazada_no_rompe_la_corrida(smtp, tmp_path, caplog):
    smtp.falla_login = True
    _historial(tmp_path / "logs", 0, "OK", "OK", "OK")
    assert notificar(tmp_path / "logs") is False
    assert "contraseña de aplicación" in caplog.text


def test_cli_notificar_siempre_devuelve_0(smtp, tmp_path):
    smtp.falla_login = True
    _historial(tmp_path / "logs", 0, "OK", "OK", "OK")
    assert cli.main(["--log-dir", str(tmp_path / "logs"), "notificar"]) == cli.EXIT_OK


def test_asunto_sin_run_id():
    asunto, cuerpo = armar_correo(
        {"fecha": "2026-10-20 06:30:00", "codigo": "1", "resultado": "ERROR_TEMPORAL"}
    )
    assert asunto == "[Shopify → Siesa] 2026-10-20 · ERROR_TEMPORAL"
    assert "ejecutar_pipeline.ps1 a mano" in cuerpo
