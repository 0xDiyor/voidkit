"""Allow ``python -m voidkit`` to invoke the CLI."""

import sys

from voidkit.cli import main

if __name__ == "__main__":
    sys.exit(main())
