"""Home Assistant flow entry point; only the canonical v3 editor is registered."""

from .config_flow_v3 import ConfigFlow, FuturaOptionsFlow  # noqa: F401
