"""Run Pico Link through HA setup, events and services, without real hardware."""

import asyncio

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockModule, mock_integration

EVENT = "lutron_caseta_button_event"
HARDWARE_TYPES = {
    "P2B": "PaddleSwitchPico",
    "2B": "Pico2Button",
    "3BRL": "Pico3ButtonRaiseLower",
    "4B": "Pico4ButtonScene",
}
SERVICES = {
    "light": ("turn_on", "turn_off"),
    "cover": ("open_cover", "close_cover", "stop_cover", "set_cover_position"),
    "fan": ("set_percentage", "turn_off", "set_direction"),
    "media_player": (
        "media_play_pause",
        "media_next_track",
        "volume_set",
        "volume_mute",
    ),
    "switch": ("turn_on", "turn_off"),
    "scene": ("turn_on",),
    "script": ("turn_on",),
}


class PicoHarness:
    """Record outgoing service calls while running the actual integration."""

    def __init__(self, hass):
        self.hass = hass
        self.calls = []
        self.received = asyncio.Queue()
        for domain, services in SERVICES.items():
            for service in services:
                self.register(domain, service)

    def register(self, domain, service, handler=None):
        async def record(call):
            item = (call.domain, call.service, dict(call.data))
            self.calls.append(item)
            self.received.put_nowait(item)
            if handler is not None:
                await handler(call)

        self.hass.services.async_register(domain, service, record)

    async def setup(self, devices, defaults=None):
        """Use short, real timers; tests do not replace gesture calculations."""
        return await async_setup_component(
            self.hass,
            "pico_link",
            {
                "pico_link": {
                    "defaults": {
                        "hold_time_ms": 100,
                        "step_time_ms": 100,
                        **(defaults or {}),
                    },
                    "devices": devices,
                }
            },
        )

    def fire(self, button, action="press", *, device="pico", kind="3BRL", **data):
        self.hass.bus.async_fire(
            EVENT,
            {
                "device_id": device,
                "type": HARDWARE_TYPES[kind],
                "button_type": button,
                "action": action,
                **data,
            },
        )

    def tap(self, button, **kwargs):
        self.fire(button, "press", **kwargs)
        self.fire(button, "release", **kwargs)

    async def next_call(self):
        return await asyncio.wait_for(self.received.get(), timeout=3)

    async def drain(self):
        await asyncio.wait_for(self.hass.async_block_till_done(), timeout=5)

    async def stop(self):
        self.hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await self.drain()


@pytest.fixture
async def pico(hass, enable_custom_integrations):
    """Fake only the Lutron bridge and device services, not Pico Link."""
    mock_integration(hass, MockModule("lutron_caseta"))
    harness = PicoHarness(hass)
    yield harness
    await harness.stop()
