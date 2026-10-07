"""Where the network lives on disk, and getting it there."""

from __future__ import annotations

import os
from pathlib import Path


def cache_dir() -> Path:
    """``$DUTCH_WATERWAYS_CACHE``, or ``~/.cache/dutch-waterways``."""
    env = os.environ.get("DUTCH_WATERWAYS_CACHE")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "dutch-waterways"


def raw_dir() -> Path:
    return cache_dir() / "raw"


def network_path() -> Path:
    return cache_dir() / "network.parquet"


def ensure_network(refresh: bool = False) -> Path:
    """Download FIS and build the network into the cache, unless already there."""
    from . import fis
    from .build import build_from_dir

    path = network_path()
    if refresh or not path.exists():
        fis.download(raw_dir())
        build_from_dir(raw_dir(), path)
    return path


_default = None


def default_network(refresh: bool = False):
    """The cached network, downloaded and built on first use (about 10 s)."""
    global _default
    if _default is None or refresh:
        from .network import Network

        _default = Network.load(ensure_network(refresh))
    return _default
