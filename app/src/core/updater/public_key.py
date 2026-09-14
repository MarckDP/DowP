# src/core/updater/public_key.py
"""Clave publica Ed25519 con la que el cliente verifica manifest.json.

Embebida como constante de Python y no como archivo de datos: un modulo viaja
SIEMPRE dentro del ejecutable congelado (en el PYZ), mientras que un .pem suelto
depende de donde PyInstaller deje los datos. La 1.9.0 buscaba el .pem junto a
__file__ -- en el .exe eso resuelve a _internal/core/updater/, pero el build lo
dejaba en _internal/src/core/updater/, asi que ningun build empaquetado pudo
verificar nunca un manifiesto (Errno 2, reportado en silencio como "sin
actualizaciones").

La escribe tools/updater/keygen.py. tools/updater/publish.py se niega a publicar
si la clave privada no corresponde a esta.
"""

UPDATER_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEANRdK223KfieDGTPDH32bHd7/U4iNazxNMGew+MeXK2U=
-----END PUBLIC KEY-----
"""
