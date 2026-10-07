"""cs2-link-manager: manage CS2 CounterStrikeSharp/Metamod plugins via symlinks."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cs2lm")
except PackageNotFoundError:  # running from source without pip install
    __version__ = "0.1.0"