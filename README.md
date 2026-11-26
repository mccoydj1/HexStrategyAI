# Hex Strategy

A four-seat desktop strategy game for one human and three computer players. The board, pieces, controls, and copy are drawn and written for this project.

## Play on Windows

Extract `HexStrategy-Windows-x64.zip` in File Explorer, open the extracted **Hex Strategy** folder, and double-click **Hex Strategy.exe**. The archive bundles Python, Tcl/Tk, and the AI checkpoints for 64-bit Windows 10 and 11. Keep the extracted folder together. Use **Save** and **Open** in the game to manage your progress.

## Run from source

Use Python 3.10 or newer with Tk. On Debian or Ubuntu, install the distribution's `python3-tk` package if `python -m tkinter` cannot open a test window. On Windows and macOS, use a Python installer that includes Tcl/Tk.

Launch from the repository root.

```sh
python -m hexstrategy
```

The application loads the selected policy and the validated placement and endgame search checkpoints when you launch it. The bundled policy runs locally with Python and Tcl/Tk.

- **Board** lets you place highlighted pieces or move the robber. Select an item in the move list and use **Play move** for any action, including ambiguous board targets, discards, cards, and supply exchanges.
- **Trade** opens a bundle editor. An incoming offer gives you a choice to accept, decline, or counter. Use **Compare offer** to simulate a draft before sending it.
- **Coach** compares up to three policy-selected actions, the highlighted action if different, and a representative domestic trade when available. You can continue playing while the simulations run. The results apply to the position you asked about. Reopening the same comparison reuses its completed simulations until a move or difficulty change.
- **Easy**, **Standard**, and **Hard** adjust the computer policy. **Save** and **Open** use a local replay file to resume any phase.

See [Rules](RULES.md), [Architecture and evaluation](EVALUATION.md), and [Licensing and provenance](PROVENANCE.md).

## Verify and reproduce

```sh
python -m unittest discover -s tests -v
python -m hexstrategy.train --workers 2 --training-games 144 --candidates 20
python -m hexstrategy.refine
python -m hexstrategy.opening_search
python -m hexstrategy.trade_search
python -m hexstrategy.validate
python -m hexstrategy.benchmark
python -m hexstrategy.benchmark --profile
python -m hexstrategy.benchmark --cpu-probe
python -m hexstrategy.tactical --holdout
python -m hexstrategy.learn
python -m hexstrategy.learn --holdout
python -m hexstrategy.economy_search
python -m hexstrategy.placement_trial
python -m hexstrategy.placement_trial --holdout
python -m hexstrategy.robber_trial
python -m hexstrategy.robber_trial --holdout
```

The display test skips when a graphical display is unavailable. With Xvfb installed, use `xvfb-run -a python -m unittest discover -s tests -v` to exercise a complete desktop match and save/resume through the GUI. Training commands replace the JSON outputs for their experiment.

The compiled benchmark is optional. With Cython 3.1.4, setuptools, and a native compiler installed, `python -m hexstrategy.compile_trial` builds and measures a temporary copy of the Python source. The desktop launch uses the standard interpreter.

## Build the Windows ZIP

The packaging script takes the official [64-bit Python 3.13.11 embeddable ZIP](https://www.python.org/ftp/python/3.13.11/python-3.13.11-embed-amd64.zip) and the installation tree extracted from the matching [Tcl/Tk MSI](https://www.python.org/ftp/python/3.13.11/amd64/tcltk.msi). The tree must contain `DLLs`, `Lib/tkinter`, and `tcl`.

```sh
python packaging/build_windows_portable.py python-3.13.11-embed-amd64.zip extracted-tcltk dist/HexStrategy-Windows-x64.zip
```

The launcher is the bundled Python windowed executable with a startup module. That module enters the graphical game when the executable is opened directly and lets worker processes start normally when given interpreter arguments.
