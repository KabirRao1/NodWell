"""PyInstaller entry script for the Nodwell executable."""

import sys

from nodwell.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
