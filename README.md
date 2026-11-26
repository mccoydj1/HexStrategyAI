# Hex Strategy

A four-seat desktop strategy game for one human and three computer players. The board, pieces, controls, and copy are drawn and written for this project.

## Launch

Use Python 3.10 or newer with Tk. On Debian or Ubuntu, install the distribution's `python3-tk` package if `python -m tkinter` cannot open a test window. On Windows and macOS, use a Python installer that includes Tcl/Tk.

Launch from the repository root.

```sh
python -m hexstrategy
```

The application loads the selected policy and the validated endgame search checkpoint when you launch it. The bundled policy runs locally with Python and Tcl/Tk.

- **Board** lets you place highlighted pieces or move the robber. Select an item in the move list and use **Play move** for any action, including ambiguous board targets, discards, cards, and supply exchanges.
- **Trade** opens a bundle editor. An incoming offer gives you a choice to accept, decline, or counter. Use **Compare offer** to simulate a draft before sending it.
- **Coach** compares up to three policy-selected actions, the highlighted action if different, and a representative domestic trade when available. You can continue playing while the simulations run. The results apply to the position you asked about.
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
python -m hexstrategy.tactical --holdout
python -m hexstrategy.learn
```

The display test skips when a graphical display is unavailable. With Xvfb installed, use `xvfb-run -a python -m unittest discover -s tests -v` to exercise a complete desktop match and save/resume through the GUI. Training commands replace the JSON outputs for their experiment.
