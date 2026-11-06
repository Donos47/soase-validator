"""Command-line entry point for sose-validator (placeholder)."""

import argparse
import sys
from collections.abc import Sequence

from sose_validator import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Run the sose-validator command-line interface.

    Args:
        argv: Command-line arguments excluding the program name. Defaults to
            ``sys.argv[1:]``.

    Returns:
        The process exit code.

    Raises:
        SystemExit: When argparse handles ``--help`` or ``--version``.
    """
    parser = argparse.ArgumentParser(
        prog="sose-validator",
        description="Validate Sins of a Solar Empire mod files.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
