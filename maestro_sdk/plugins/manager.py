"""Plugin architecture for Maestro SDK.

Plugins are discoverable, loadable extensions that hook into the ConnectionBroker lifecycle.
"""
import abc
import logging
from typing import Dict, Any, Optional

log = logging.getLogger("maestro.plugins")

class Plugin(abc.ABC):
    """Base class for Maestro plugins.

    Plugins must be concrete subclasses. The PluginManager registers
    them by name and calls setup/teardown around the broker lifecycle.
    """
    name: str = ""
    version: str = "0.1"

    @abc.abstractmethod
    async def setup(self, broker, config: Dict[str, Any]) -> bool:
        """Called once when the broker starts. Return False to disable."""
        pass

    @abc.abstractmethod
    async def teardown(self):
        """Called when the broker stops."""
        pass

# Registry of built-in plugins
_BUILTINS = {}

def register_builtin(plugin_cls):
    _BUILTINS[plugin_cls.name] = plugin_cls
    return plugin_cls

class PluginManager:
    def __init__(self, broker):
        self.broker = broker
        self._plugins: Dict[str, Plugin] = {}

    def register(self, plugin: Plugin):
        self._plugins[plugin.name] = plugin

    async def load(self, name: str, config: Dict[str, Any]) -> bool:
        plugin = self._plugins.get(name)
        if not plugin:
            log.error(f"Plugin {name} not found")
            return False
        try:
            ok = await plugin.setup(self.broker, config)
            if ok:
                log.info(f"Plugin {name} v{plugin.version} loaded")
            else:
                log.warning(f"Plugin {name} setup returned False — disabled")
            return ok
        except Exception as e:
            log.error(f"Plugin {name} setup failed: {e}")
            return False

    async def unload_all(self):
        for name, plugin in self._plugins.items():
            try:
                await plugin.teardown()
                log.info(f"Plugin {name} unloaded")
            except Exception as e:
                log.error(f"Plugin {name} teardown error: {e}")
