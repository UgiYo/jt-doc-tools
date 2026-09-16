"""GPU OCR server remote deployment helpers.

The install-script generator supports both normal online installation and a
fully air-gapped wheelhouse mode.  The generated script uses online behaviour
by default; set JT_OCR_OFFLINE=1 on the GPU host for offline installation.
"""
from .offline_builder import build_install_script, build_uninstall_script

__all__ = ["build_install_script", "build_uninstall_script"]
