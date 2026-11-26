"""Benchmark optional compilation of the existing Python sources in a temporary copy."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory

from .train import ARTIFACTS, save

BUILD = """
from setuptools import Extension, setup
from Cython.Build import cythonize

extensions = [Extension("hexstrategy." + name, [f"hexstrategy/{name}.py"])
              for name in ("ai", "game")]
setup(ext_modules=cythonize(extensions, compiler_directives={
    "language_level": 3, "annotation_typing": False,
}))
"""


def main():
    from Cython import __version__ as cython_version

    project = ARTIFACTS.parent
    environment = os.environ.copy()
    compiler = (sysconfig.get_config_var("CC") or "").split()
    if (compiler and "CC" not in environment and not shutil.which(compiler[0])
            and shutil.which("gcc")):
        environment["CC"] = "gcc"
        environment["LDSHARED"] = "gcc -shared"
    with TemporaryDirectory(prefix="hexstrategy-compile-") as directory:
        workspace = Path(directory)
        shutil.copytree(project / "hexstrategy", workspace / "hexstrategy",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (workspace / "artifacts").mkdir()
        shutil.copy2(ARTIFACTS / "policy.json", workspace / "artifacts")
        (workspace / "build_trial.py").write_text(BUILD)
        subprocess.run([sys.executable, "build_trial.py", "build_ext", "--inplace"],
                       cwd=workspace, env=environment, check=True)
        subprocess.run([sys.executable, "-m", "hexstrategy.benchmark",
                        "--output", "coaching-cython.json"],
                       cwd=workspace, env=environment, check=True)
        evidence = json.loads((workspace / "artifacts/coaching-cython.json").read_text())
    evidence["environment"]["backend"] = f"Cython {cython_version} compiled Python modules"
    evidence["environment"]["compiler"] = environment.get("CC", " ".join(compiler))
    save("coaching-cython.json", evidence)


if __name__ == "__main__":
    main()
