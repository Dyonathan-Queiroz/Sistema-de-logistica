"""
build_exe.py — Build automatizado do PDV Entregas

Uso:
    python build_exe.py            # build completo (PyInstaller + Inno Setup)
    python build_exe.py --only-exe # só o .exe (sem gerar instalador)
    python build_exe.py --only-iss # só o instalador (usa dist\\ existente)

O script:
  1. Garante que o PyInstaller está instalado.
  2. Roda o PyInstaller usando "PDV Entregas.spec".
  3. Localiza o ISCC.exe do Inno Setup (verifica caminhos comuns).
  4. Compila o pdv_instalador.iss gerando Output\PDV_Entregas_Setup_1.0.exe.
"""

import subprocess
import sys
import os
import shutil
import argparse

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC_FILE = os.path.join(ROOT, "PDV Entregas.spec")
ISS_FILE  = os.path.join(ROOT, "pdv_instalador.iss")
DIST_EXE  = os.path.join(ROOT, "dist", "PDV Entregas", "PDV Entregas.exe")
OUTPUT_INSTALLER = os.path.join(ROOT, "Output", "PDV_Entregas_Setup_1.0.exe")

ISCC_SEARCH_PATHS = [
    r"C:\Users\{user}\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], desc: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {desc}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"\n[ERRO] Falhou com código {result.returncode}. Abortando.")
        sys.exit(result.returncode)


def _find_iscc() -> str | None:
    # Tenta shutil.which primeiro (funciona se ISCC está no PATH)
    found = shutil.which("ISCC") or shutil.which("ISCC.exe")
    if found:
        return found

    user = os.environ.get("USERNAME", "")
    for pattern in ISCC_SEARCH_PATHS:
        path = pattern.replace("{user}", user)
        if os.path.isfile(path):
            return path

    return None


def _ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller não encontrado. Instalando...")
        _run([sys.executable, "-m", "pip", "install", "pyinstaller"], "pip install pyinstaller")


# ---------------------------------------------------------------------------
# Etapas de build
# ---------------------------------------------------------------------------

def build_exe() -> None:
    _ensure_pyinstaller()
    _run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", SPEC_FILE],
        "PyInstaller — gerando dist\\PDV Entregas\\",
    )
    if not os.path.isfile(DIST_EXE):
        print(f"[ERRO] Executável não encontrado após o build: {DIST_EXE}")
        sys.exit(1)
    size_mb = os.path.getsize(DIST_EXE) / 1024 / 1024
    print(f"\n[OK] {DIST_EXE}  ({size_mb:.1f} MB)")


def build_installer() -> None:
    iscc = _find_iscc()
    if not iscc:
        print(
            "\n[AVISO] ISCC.exe não encontrado.\n"
            "  Instale o Inno Setup 6 em: https://jrsoftware.org/isinfo.php\n"
            "  Ou execute: winget install JRSoftware.InnoSetup --accept-source-agreements\n"
            "  Depois rode: python build_exe.py --only-iss"
        )
        sys.exit(1)

    _run([iscc, ISS_FILE], "Inno Setup — gerando instalador")

    if os.path.isfile(OUTPUT_INSTALLER):
        size_mb = os.path.getsize(OUTPUT_INSTALLER) / 1024 / 1024
        print(f"\n[OK] {OUTPUT_INSTALLER}  ({size_mb:.1f} MB)")
    else:
        print(f"[AVISO] Instalador não encontrado em {OUTPUT_INSTALLER}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build do PDV Entregas")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--only-exe", action="store_true", help="Gera apenas o .exe (sem instalador)")
    group.add_argument("--only-iss", action="store_true", help="Gera apenas o instalador (usa dist\\ existente)")
    args = parser.parse_args()

    if args.only_exe:
        build_exe()
    elif args.only_iss:
        build_installer()
    else:
        build_exe()
        build_installer()

    print("\n✔ Build finalizado com sucesso.\n")


if __name__ == "__main__":
    main()
