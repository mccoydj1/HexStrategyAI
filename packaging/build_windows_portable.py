"""Create the Windows game ZIP from matching official CPython and Tk files."""
import argparse
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINTS = ("policy.json", "tactical-holdout.json", "placement-holdout.json")

INSTRUCTIONS = """Hex Strategy for Windows 10 and 11 (64-bit)

1. In File Explorer, right-click the ZIP and choose Extract All.
2. Open the extracted Hex Strategy folder.
3. Double-click Hex Strategy.exe.

Keep the launcher and runtime files together. The game includes Python, Tcl/Tk,
and the AI checkpoints. Use Save and Open in the game to manage your progress.

The Rules button gives a quick overview. Open RULES.md in a text editor for the
complete rules. The included license files cover the game and bundled runtime.
"""


def build(embedded, tkinter, output):
    with TemporaryDirectory(prefix="hexstrategy-windows-") as directory:
        temp = Path(directory)
        game = temp / "Hex Strategy"
        game.mkdir()
        with ZipFile(embedded) as archive:
            archive.extractall(game)
        for name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll"):
            shutil.copy2(tkinter / "DLLs" / name, game)
        shutil.copytree(tkinter / "Lib" / "tkinter", game / "tkinter")
        shutil.copytree(tkinter / "tcl", game / "tcl", ignore=shutil.ignore_patterns("nmake", "demos"))
        if not all((game / "tcl" / path).is_file()
                   for path in ("tcl8.6/init.tcl", "tk8.6/tk.tcl")):
            raise ValueError("The Tk files must include Tcl and Tk 8.6 script libraries.")

        (game / "pythonw.exe").rename(game / "Hex Strategy.exe")
        (game / "python.exe").unlink()
        (game / "LICENSE.txt").rename(game / "Python-LICENSE.txt")
        (game / "python313._pth").write_text("python313.zip\n.\nimport site\n", encoding="utf-8")
        shutil.copy2(ROOT / "packaging" / "windows_startup.py", game / "sitecustomize.py")

        package = game / "hexstrategy"
        package.mkdir()
        for source in (ROOT / "hexstrategy").glob("*.py"):
            shutil.copy2(source, package)
        artifacts = game / "artifacts"
        artifacts.mkdir()
        for name in CHECKPOINTS:
            shutil.copy2(ROOT / "artifacts" / name, artifacts)
        for name in ("LICENSE", "RULES.md", "PROVENANCE.md"):
            shutil.copy2(ROOT / name, game)
        shutil.copy2(tkinter / "tcl" / "tk8.6" / "license.terms", game / "Tcl-Tk-LICENSE.txt")
        shutil.copy2(ROOT / "packaging" / "Zlib-LICENSE.txt", game)
        (game / "Start Here.txt").write_text(INSTRUCTIONS, encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.make_archive(str(output.with_suffix("")), "zip", temp, game.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("embedded", type=Path, help="official Python 3.13 x64 embeddable ZIP")
    parser.add_argument("tkinter", type=Path, help="extracted matching tcltk.msi install tree")
    parser.add_argument("output", type=Path, help="target ZIP filename")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".zip":
        parser.error("output must end in .zip")
    build(args.embedded, args.tkinter, args.output)


if __name__ == "__main__":
    main()
