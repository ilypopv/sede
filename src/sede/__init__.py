"""Top-level package for the sede CLI application."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("sede")
except PackageNotFoundError:
    __version__ = "0+unknown"
