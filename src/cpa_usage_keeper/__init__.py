"""CPA Usage Keeper - CPA usage persistence and visualization service."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("cpa-usage-keeper")
except PackageNotFoundError:
    __version__ = "0.0.0"
