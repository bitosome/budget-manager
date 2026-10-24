"""Panel startup keeps asset I/O off the event loop and preserves cache keys."""

import asyncio
from hashlib import sha256
import importlib
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import test_model as support  # Set up the existing standard-library HA fixtures.


class PanelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        components = ModuleType("homeassistant.components")
        components.__path__ = []
        components.frontend = SimpleNamespace()
        components.panel_custom = SimpleNamespace(async_register_panel=AsyncMock())
        http = ModuleType("homeassistant.components.http")
        http.StaticPathConfig = lambda *args: args
        with patch.dict(sys.modules, {components.__name__: components, http.__name__: http}):
            self.panel = importlib.import_module("custom_components.budget_manager.panel")
        self.register = self.panel.panel_custom.async_register_panel
        self.register.reset_mock()
        self.hass = SimpleNamespace(
            data={},
            async_add_executor_job=asyncio.to_thread,
            http=SimpleNamespace(async_register_static_paths=AsyncMock()),
        )

    async def test_asset_hash_is_read_in_worker_and_used_for_both_cache_keys(self):
        loop_thread = threading.get_ident()
        asset = b"customElements.define('budget-manager-panel', class {});"

        def read_asset(path):
            self.assertNotEqual(threading.get_ident(), loop_thread)
            self.assertEqual(path.name, "budget-manager-panel.js")
            return asset

        with patch.object(Path, "read_bytes", read_asset):
            await self.panel.async_register_panel(self.hass)

        digest = sha256(asset).hexdigest()[:12]
        config = self.register.call_args.kwargs
        self.assertEqual(config["webcomponent_name"], f"budget-manager-panel-{digest}")
        self.assertEqual(config["module_url"], f"/budget_manager_frontend/budget-manager-panel.js?v={digest}")
        self.assertTrue(config["handle_safe_area"])
        self.hass.http.async_register_static_paths.assert_awaited_once()
        self.register.assert_awaited_once()

    async def test_failed_asset_read_does_not_register_partial_panel(self):
        with patch.object(Path, "read_bytes", side_effect=OSError("asset unavailable")):
            with self.assertRaisesRegex(OSError, "asset unavailable"):
                await self.panel.async_register_panel(self.hass)
        self.hass.http.async_register_static_paths.assert_not_awaited()
        self.register.assert_not_awaited()
