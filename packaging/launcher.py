"""PyInstaller entry point for the windowed Extract.exe."""

import multiprocessing

from extract.gui.app import main

if __name__ == "__main__":
    # The CPU benchmark uses a "spawn" process pool; in a frozen exe each worker re-runs
    # this script, and freeze_support() turns it into a worker instead of a second GUI.
    multiprocessing.freeze_support()
    raise SystemExit(main())
