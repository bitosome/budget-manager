"""Register the Budget Manager sidebar panel."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL,
    STATIC_URL,
)


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register frontend assets and the full-screen custom panel."""
    frontend_path = Path(__file__).parent / "frontend"
    panel_path = frontend_path / "budget-manager-panel.js"
    panel_version = sha256(panel_path.read_bytes()).hexdigest()[:12]
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(frontend_path), False)]
    )
    if PANEL_URL in hass.data.get("frontend_panels", {}):
        return
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_COMPONENT,
        frontend_url_path=PANEL_URL,
        module_url=f"{STATIC_URL}/budget-manager-panel.js?v={panel_version}",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=False,
        config={},
        config_panel_domain=DOMAIN,
    )


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel."""
    frontend.async_remove_panel(hass, PANEL_URL)
