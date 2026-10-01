"""async_release_script against each shape Home Assistant's script registry has had."""

from __future__ import annotations

from homeassistant.helpers.script import DATA_SCRIPTS

from custom_components.pico_link.utilities import async_release_script


class _SelfUnloadingScript:
    """A Script from Home Assistant 2026.9+, which deregisters itself."""

    def __init__(self) -> None:
        self.unloaded = False
        self.stopped = False

    async def async_unload(self) -> None:
        self.unloaded = True

    async def async_stop(self) -> None:
        self.stopped = True


class _LegacyScript:
    """A Script from before async_unload existed, leaving the registry to us."""

    def __init__(self) -> None:
        self.stopped = False

    async def async_stop(self) -> None:
        self.stopped = True


async def test_prefers_home_assistants_own_unload(hass) -> None:
    """async_unload stops the script and deregisters it, so we do neither."""
    script = _SelfUnloadingScript()
    hass.data[DATA_SCRIPTS] = {id(script): {"instance": script}}

    await async_release_script(hass, script)

    assert script.unloaded
    assert not script.stopped
    # Left alone deliberately: deregistering is async_unload's job, and
    # doing it here would mean knowing a registry shape we no longer touch.
    assert id(script) in hass.data[DATA_SCRIPTS]


async def test_dict_registry_drops_the_script(hass) -> None:
    """HA 2026.9 keys the registry by id(script) rather than listing entries."""
    script = _LegacyScript()
    other = _LegacyScript()

    hass.data[DATA_SCRIPTS] = {
        id(script): {"instance": script, "started_before_shutdown": True},
        id(other): {"instance": other, "started_before_shutdown": True},
    }

    await async_release_script(hass, script)

    assert script.stopped
    assert list(hass.data[DATA_SCRIPTS]) == [id(other)]


async def test_list_registry_drops_the_script(hass) -> None:
    """Pre-2026.9 HA listed {"instance": ...} entries instead."""
    script = _LegacyScript()
    other = _LegacyScript()

    hass.data[DATA_SCRIPTS] = [
        {"instance": script, "started_before_shutdown": True},
        {"instance": other, "started_before_shutdown": True},
    ]

    await async_release_script(hass, script)

    assert script.stopped
    assert [item["instance"] for item in hass.data[DATA_SCRIPTS]] == [other]


async def test_empty_registry_is_not_an_error(hass) -> None:
    """A script released before anything registered must not raise."""
    script = _LegacyScript()
    hass.data.pop(DATA_SCRIPTS, None)

    await async_release_script(hass, script)

    assert script.stopped
