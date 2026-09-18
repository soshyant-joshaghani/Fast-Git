"""Local helper: create/refresh Fast-Git .venv."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from lib.config import ROOT
from lib.ssh import echo

CTRL = "fast-git"


def cmd_setup_local(args: argparse.Namespace) -> int:
    """Create or refresh .venv + pip install -r requirements.txt."""
    venv = ROOT / ".venv"
    if bool(getattr(args, "force", False)) and venv.is_dir():
        echo(f"[{CTRL}] Removing existing .venv (--force)...")
        shutil.rmtree(venv)

    py = sys.executable
    if not (venv / ("Scripts" if sys.platform == "win32" else "bin") / "python").exists():
        echo(f"[{CTRL}] Creating .venv...")
        code = subprocess.call([py, "-m", "venv", str(venv)])
        if code != 0:
            return code

    if sys.platform == "win32":
        pip = venv / "Scripts" / "pip.exe"
        vpy = venv / "Scripts" / "python.exe"
    else:
        pip = venv / "bin" / "pip"
        vpy = venv / "bin" / "python"

    echo(f"[{CTRL}] Installing requirements.txt...")
    code = subprocess.call([str(vpy), "-m", "pip", "install", "--upgrade", "pip"])
    if code != 0:
        return code
    return subprocess.call([str(pip), "install", "-r", str(ROOT / "requirements.txt")])


def build_setup_local_subparser(sub: argparse._SubParsersAction) -> None:
    sp = sub.add_parser(
        "setup-local",
        help="Create/refresh .venv and install requirements.txt",
    )
    sp.add_argument(
        "--force",
        action="store_true",
        help="Delete .venv before recreating",
    )
    sp.set_defaults(func=cmd_setup_local)
