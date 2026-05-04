"""
Ponto de entrada do executável PDV Entregas.
Este arquivo é usado pelo PyInstaller como script raiz.

Importa diretamente pdv_gui.main_window para que o PyInstaller consiga
rastrear todas as dependências (PyQt6, pynput, win32, etc.) em tempo de build.
"""
import sys
import os

# Garante que a pasta raiz está no path (necessário quando rodando como .exe)
if getattr(sys, "frozen", False):
    _base = os.path.dirname(sys.executable)
else:
    _base = os.path.dirname(os.path.abspath(__file__))

if _base not in sys.path:
    sys.path.insert(0, _base)

from pdv_gui.main_window import main

main()
