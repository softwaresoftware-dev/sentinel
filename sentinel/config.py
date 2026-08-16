"""Alias — sentinel's own settings live in sentinel.core (single config file for the whole stack)."""
from .core import CONFIG_DIR, CONFIG_PATH, DATA_DIR, DEFAULTS, load, save  # noqa: F401
