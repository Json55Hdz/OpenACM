"""OpenACM - Open Automated Computer Manager."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("openacm")
except PackageNotFoundError:
    __version__ = "0.0.0"
