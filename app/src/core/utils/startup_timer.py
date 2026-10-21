# src/core/utils/startup_timer.py
"""Marcas de tiempo del arranque, para medir en el log cuánto tarda cada fase en
cada sistema (en especial en el compilado y en frío, que es donde más se nota).

Cada línea sale como "Arranque: <fase> -- 1.23s (+0.45s)": el primer número es el
tiempo desde que main.py empezó a importar, el segundo lo que tardó desde la marca
anterior. El reloj arranca al importar este módulo, por eso main.py lo importa antes
que nada. Lo que pasa antes de eso (el intérprete y el bootloader de PyInstaller) no
se ve aquí."""
import threading
import time

_T0 = time.perf_counter()
_last = _T0
_lock = threading.Lock()
_finished = False


def mark(phase: str) -> None:
    global _last
    now = time.perf_counter()
    with _lock:
        delta = now - _last
        _last = now
    # Import diferido: la primera marca puede llegar antes de que el logger exista.
    from core.logger.logger_manager import logger
    logger.info(f"Arranque: {phase} -- {now - _T0:.2f}s (+{delta:.2f}s)")


class measure:
    """`with measure("fase"):` deja en el log cuánto tardó el bloque por sí solo, sin
    mover la marca de mark() (sirve para fases que corren en otro hilo en paralelo)."""

    def __init__(self, phase: str):
        self.phase = phase

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        end = time.perf_counter()
        from core.logger.logger_manager import logger
        logger.info(f"Arranque: {self.phase} -- {end - self._start:.2f}s (a los {end - _T0:.2f}s)")
        return False


def finish(phase: str = "arranque completo") -> None:
    """Última marca del arranque; las siguientes llamadas no hacen nada."""
    global _finished
    if _finished:
        return
    _finished = True
    mark(phase)
