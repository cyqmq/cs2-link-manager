"""Allow running as `python -m cs2lm`."""
import sys

from cs2lm.cli import main

if __name__ == "__main__":
    sys.exit(main())