"""`python -m extract`: opens the GUI, or the CLI when a CLI command is given."""

import sys

CLI_COMMANDS = {"scan", "export", "--version", "-h", "--help"}


def main() -> int:
    if CLI_COMMANDS.intersection(sys.argv[1:2]):
        from extract.cli import main as cli_main

        return cli_main()
    from extract.gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
