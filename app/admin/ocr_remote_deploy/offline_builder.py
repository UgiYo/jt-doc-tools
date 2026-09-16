"""Air-gapped aware wrapper for the GPU OCR deployment script.

Online behaviour stays unchanged.  Set JT_OCR_OFFLINE=1 on the GPU host and
place all Python wheels under JT_OCR_WHEELHOUSE (default: /tmp/jt-ocr-wheelhouse)
to install without reaching apt/PyPI/download.pytorch.org.
"""
from __future__ import annotations

from .builder import build_install_script as _online_build_install_script
from .builder import build_uninstall_script


def build_install_script(*, jtdt_version: str = "unknown") -> str:
    script = _online_build_install_script(jtdt_version=jtdt_version)

    apt_old = 'apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv curl'
    apt_new = '''if [ "${JT_OCR_OFFLINE:-0}" = "1" ]; then
    echo "[offline] skipping apt-get; python3 + venv must already exist on this host"
    command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required" >&2; exit 1; }
    python3 -m venv --help >/dev/null 2>&1 || { echo "ERROR: python3-venv is required" >&2; exit 1; }
else
    apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv curl
fi'''
    if apt_old not in script:
        raise RuntimeError("GPU OCR installer template changed: apt block not found")
    script = script.replace(apt_old, apt_new, 1)

    pip_old = '''"$PIP" install --upgrade pip -q

# PyTorch CUDA 12.4 wheel — works on driver >= 550 (H100/H200/4090/DGX Spark)
echo "[2/5] Installing PyTorch CUDA (this is ~3 GB)..."
"$PIP" install torch torchvision --index-url https://download.pytorch.org/whl/cu124 -q

# EasyOCR + FastAPI
echo "[3/5] Installing EasyOCR + server deps..."
"$PIP" install easyocr fastapi "uvicorn[standard]" python-multipart pillow numpy -q'''
    pip_new = '''if [ "${JT_OCR_OFFLINE:-0}" = "1" ]; then
    WHEELHOUSE="${JT_OCR_WHEELHOUSE:-/tmp/jt-ocr-wheelhouse}"
    [ -d "$WHEELHOUSE" ] || { echo "ERROR: offline wheelhouse not found: $WHEELHOUSE" >&2; exit 1; }
    echo "[2/5] Installing PyTorch from offline wheelhouse..."
    "$PIP" install --no-index --find-links "$WHEELHOUSE" torch torchvision
    echo "[3/5] Installing EasyOCR + server deps from offline wheelhouse..."
    "$PIP" install --no-index --find-links "$WHEELHOUSE" easyocr fastapi "uvicorn[standard]" python-multipart pillow numpy
else
    "$PIP" install --upgrade pip -q
    echo "[2/5] Installing PyTorch CUDA (this is ~3 GB)..."
    "$PIP" install torch torchvision --index-url https://download.pytorch.org/whl/cu124 -q
    echo "[3/5] Installing EasyOCR + server deps..."
    "$PIP" install easyocr fastapi "uvicorn[standard]" python-multipart pillow numpy -q
fi'''
    if pip_old not in script:
        raise RuntimeError("GPU OCR installer template changed: pip block not found")
    script = script.replace(pip_old, pip_new, 1)

    marker = '# JT-Doc-Tools External OCR Server installer'
    script = script.replace(marker, marker + '''
# Air-gapped mode:
#   export JT_OCR_OFFLINE=1
#   export JT_OCR_WHEELHOUSE=/tmp/jt-ocr-wheelhouse
#   bash jt-ocr-server-install.sh --dry-run
#   bash jt-ocr-server-install.sh
# In offline mode this script performs ZERO apt/PyPI/PyTorch-index downloads.
''', 1)
    return script


__all__ = ["build_install_script", "build_uninstall_script"]
