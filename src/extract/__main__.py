"""`python -m extract`: opens the GUI, or the CLI when arguments are given."""

import sys


def main() -> int:
    if len(sys.argv) > 1:
        from extract.cli import main as cli_main

        return cli_main()
    from extract.gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
