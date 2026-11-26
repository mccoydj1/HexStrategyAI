"""Start the GUI when the bundled Windows launcher is double-clicked."""
import os
from pathlib import Path
import sys


def launch():
    root = Path(sys.executable).resolve().parent
    os.environ["TCL_LIBRARY"] = str(root / "tcl" / "tcl8.6")
    os.environ["TK_LIBRARY"] = str(root / "tcl" / "tk8.6")
    try:
        from hexstrategy.__main__ import main

        main()
    except Exception:
        from ctypes import windll
        from traceback import format_exc

        windll.user32.MessageBoxW(
            None, format_exc() + "\nExtract the complete game folder before launching.",
            "Hex Strategy could not start", 0x10,
        )


if (sys.platform == "win32" and len(sys.orig_argv) == 1
        and Path(sys.executable).name.casefold() == "hex strategy.exe"):
    launch()
