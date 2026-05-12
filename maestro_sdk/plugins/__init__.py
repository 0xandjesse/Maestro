"""Maestro plugins — discoverable extensions."""
from .manager import Plugin, PluginManager
from .calendar_trigger import CalendarTriggerPlugin

__all__ = ["Plugin", "PluginManager", "CalendarTriggerPlugin"]
