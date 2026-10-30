# src/core/utils/tls_certs.py
"""Certificados TLS para los programas que DowP lanza por su cuenta (ffmpeg sobre todo).

En macOS el ffmpeg de martin-riedl trae OpenSSL estático, compilado para buscar los
certificados en "/Volumes/ffmpeg_arm64/tool/openssl/cert.pem", una ruta que solo existe
en la máquina donde se compiló. Cuando ffmpeg abre https él mismo (los fragmentos con
download_ranges, que yt-dlp delega en FFmpegFD), el handshake falla y sale con
"ffmpeg exited with code 251" (EIO), sin ningún mensaje: yt-dlp no captura su stderr.
Las descargas completas no fallan porque las baja Python, y ffmpeg solo une archivos
locales.

Confirmado en una MacBook Air (2026-10-24): el mismo fragmento fallaba tres veces con
251 y bajó bien con SSL_CERT_FILE=/etc/ssl/cert.pem. OpenSSL lee esa variable, así que
basta con ponerla en el entorno del proceso: la heredan ffmpeg, yt-dlp y todo lo que
se lance después.

En Windows ffmpeg usa los certificados del sistema (schannel) y en Linux las rutas
estándar ya existen: ahí no se toca nada."""
import os
import sys

from core.logger.logger_manager import logger

# Almacén de certificados del propio macOS: viene en todas las versiones modernas y se
# actualiza con el sistema.
_MACOS_SYSTEM_BUNDLE = "/etc/ssl/cert.pem"


def _usable(path: str | None) -> bool:
    return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0


def ensure_ssl_cert_file() -> None:
    """En macOS, apunta SSL_CERT_FILE a un almacén de certificados que exista, si no lo
    hace ya. Respeta el valor del usuario mientras apunte a un archivo real."""
    if sys.platform != "darwin":
        return

    actual = os.environ.get("SSL_CERT_FILE")
    if _usable(actual):
        logger.info(f"TLS: SSL_CERT_FILE ya definido ({actual}). Respetando.")
        return

    candidato = _MACOS_SYSTEM_BUNDLE if _usable(_MACOS_SYSTEM_BUNDLE) else None
    if not candidato:
        # Respaldo: el de certifi, que ya viene con requests.
        try:
            import certifi
            if _usable(certifi.where()):
                candidato = certifi.where()
        except Exception:
            pass

    if not candidato:
        logger.warning("TLS: no se encontró ningún almacén de certificados; ffmpeg puede "
                       "fallar al abrir https (fragmentos).")
        return

    os.environ["SSL_CERT_FILE"] = candidato
    if actual:
        logger.info(f"TLS: SSL_CERT_FILE apuntaba a un archivo inexistente ({actual}); "
                    f"ahora -> {candidato}")
    else:
        logger.info(f"TLS: SSL_CERT_FILE -> {candidato}")
