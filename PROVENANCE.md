# Licensing and provenance

The repository's Python source, interface copy, written rules, and programmatic artwork were created for HexStrategyAI and are distributed under [0BSD](LICENSE). The board, buildings, trade markers, and application styling are drawn with Tk canvas primitives. Distributed visual and written assets are project originals. Tk uses the user's installed system fonts.

Python and its standard library are provided under the [Python Software Foundation license](https://docs.python.org/3/license.html). The desktop interface uses the system's Tcl and Tk runtime, available under [Tcl/Tk's permissive license](https://www.tcl-lang.org/software/tcltk/license.html). Runtime dependencies consist of Python and Tcl/Tk. Xvfb was used as a test display and is optional.

The publisher's rules and FAQ were consulted for gameplay mechanics. HexStrategyAI is an independent project. CATAN is a third-party name. The game uses the Hex Strategy brand. [Official rules](https://www.catan.com/understand-catan/game-rules) · [Base-game FAQ](https://www.catan.com/faq/basegame)

JSON files under `artifacts` contain measured program outputs and numerical policy weights produced by the commands in the README.

The temporary compiled benchmark used Cython 3.1.4 under the Apache License 2.0 and GCC as a build tool. The application ships Python source and uses the standard Python runtime. [Cython license](https://github.com/cython/cython/blob/3.1.4/LICENSE.txt)

The Windows ZIP bundles the official 64-bit Python 3.13.11 embeddable runtime and Tcl/Tk 8.6.15 files from that version’s Windows installer. The runtime’s license, Tcl/Tk’s license, and the zlib license travel with the ZIP. The launcher is a renamed copy of CPython’s original windowed executable. [CPython release](https://www.python.org/downloads/release/python-31311/) · [zlib license](https://zlib.net/zlib_license.html)
