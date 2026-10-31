"""Salida final del proceso, sin la limpieza del intérprete."""
import os
import sys


def hard_exit(code: int = 0):
    """Termina ya, con este código de salida. Quien llama ya volcó logs y salidas.

    En Windows no se usa os._exit: pasa por ExitProcess, que corre la limpieza de cada DLL, y con
    Qt Multimedia cargado (QMediaPlayer, QAudioOutput) esa limpieza puede trabarse para siempre:
    la ventana ya se cerró pero el proceso queda vivo con un solo hilo. TerminateProcess se la
    salta; el sistema libera memoria y archivos igual."""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), int(code) & 0xFFFFFFFF)
    os._exit(code)  # otros sistemas, o si lo anterior fallara
