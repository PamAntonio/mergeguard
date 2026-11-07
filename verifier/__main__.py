"""Allow `python -m verifier ...`."""

import sys

from verifier.cli import main

if __name__ == "__main__":
    sys.exit(main())
