"""Update-All Plugins package.

This package contains plugin implementations for various package managers.
"""

from plugins.base import BasePlugin
from plugins.registry import PluginRegistry

__all__ = ["BasePlugin", "PluginRegistry"]
