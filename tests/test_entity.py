"""Entity listeners must run on the event loop, not in HA's executor."""

import asyncio
import importlib
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import test_model as support  # Set up the existing standard-library HA fixtures.


def is_hass_callback(func) -> bool:
    """Same rule as homeassistant.core.is_callback."""
    return getattr(func, "_hass_callback", False) is True


class _Entity:
    async def async_added_to_hass(self) -> None:
        return None

    def async_on_remove(self, func) -> None:
        self.removers.append(func)


class EntityListenerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        helpers_entity = ModuleType("homeassistant.helpers.entity")
        helpers_entity.Entity = _Entity
        helpers_entity.DeviceInfo = dict
        sys.modules.pop("custom_components.budget_manager.entity", None)
        with patch.dict(sys.modules, {helpers_entity.__name__: helpers_entity}):
            self.module = importlib.import_module("custom_components.budget_manager.entity")
        self.addCleanup(sys.modules.pop, "custom_components.budget_manager.entity", None)

    async def _added_entity(self):
        tracked = []
        manager = SimpleNamespace(
            entry_id="entry",
            listeners=[],
            add_listener=lambda listener: manager.listeners.append(listener) or (lambda: None),
        )
        entity = self.module.BudgetEntity(manager, "key")
        entity.removers = []
        entity.hass = object()
        loop_thread = threading.get_ident()
        entity.write_threads = []
        entity.async_write_ha_state = lambda: entity.write_threads.append(threading.get_ident())

        def track(hass, action, **schedule):
            tracked.append((hass, action, schedule))
            return lambda: None

        with patch.object(self.module, "async_track_time_change", track):
            await entity.async_added_to_hass()
        return entity, manager, tracked, loop_thread

    async def test_day_change_listener_is_a_loop_callback(self):
        entity, _manager, tracked, loop_thread = await self._added_entity()

        self.assertEqual(len(tracked), 1)
        hass, action, schedule = tracked[0]
        self.assertIs(hass, entity.hass)
        self.assertEqual(schedule, {"hour": 0, "minute": 0, "second": 0})
        # HA runs non-callback sync listeners in the executor, where
        # async_write_ha_state raises the thread-safety error at midnight.
        self.assertTrue(is_hass_callback(action))
        self.assertFalse(asyncio.iscoroutinefunction(action))

        action(None)
        self.assertEqual(entity.write_threads, [loop_thread])

    async def test_manager_listener_is_a_loop_callback(self):
        entity, manager, _tracked, loop_thread = await self._added_entity()

        self.assertEqual(len(manager.listeners), 1)
        self.assertTrue(is_hass_callback(manager.listeners[0]))
        manager.listeners[0]()
        self.assertEqual(entity.write_threads, [loop_thread])


if __name__ == "__main__":
    unittest.main()
