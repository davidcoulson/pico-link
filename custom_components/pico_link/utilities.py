from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, Optional, cast

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.script import Script

from .const import DOMAIN, DOMAIN_ENTITY_FIELDS

if TYPE_CHECKING:
    from .controller import PicoController

_LOGGER = logging.getLogger(__name__)


class SharedUtils:
    """
    Shared entity-resolution and service-execution helpers.

    Domain-specific gesture state remains owned by the action modules.
    """

    def __init__(self, ctrl: "PicoController") -> None:
        self.ctrl = ctrl
        self.hass: HomeAssistant = ctrl.hass
        self.conf = ctrl.conf

        # Convert configured millisecond values once for use by
        # tap-versus-hold and ramp behavior.
        self._hold_time = self.conf.hold_time_ms / 1000.0
        self._step_time = self.conf.step_time_ms / 1000.0

        # One Script per configured action list, built lazily on first
        # use and kept for the controller's lifetime. Every top-level
        # Script registers itself in hass.data["helpers.script"] for as
        # long as it exists, so constructing a fresh one per button
        # press would leak an entry there on every press. Keyed by the
        # list's identity: every caller passes a list held on
        # self.conf, so the key is stable and the entry also pins the
        # list so its id can't be reused.
        self._scripts: dict[int, tuple[list[dict[str, Any]], Script]] = {}

    # =============================================================
    # ENTITY RESOLUTION
    # =============================================================

    def entities_for_domain(self, domain: str) -> list[str]:
        """Return all configured entities for a supported domain."""
        field_name = DOMAIN_ENTITY_FIELDS.get(domain)

        if field_name is None:
            return []

        return cast(
            list[str],
            getattr(self.conf, field_name),
        )

    def entity_domain(self) -> Optional[str]:
        """Return the single configured entity domain."""
        for domain in DOMAIN_ENTITY_FIELDS:
            if self.entities_for_domain(domain):
                return domain

        return None

    def primary_entity(
        self,
        domain: Optional[str] = None,
    ) -> Optional[str]:
        """Return the first configured entity for a domain."""
        selected_domain = domain or self.entity_domain()

        if selected_domain is None:
            return None

        entities = self.entities_for_domain(selected_domain)

        return entities[0] if entities else None

    def get_entity_state(
        self,
        domain: Optional[str] = None,
    ):
        """Return the state of the primary configured entity."""
        entity_id = self.primary_entity(domain)

        if entity_id is None:
            return None

        return self.hass.states.get(entity_id)

    # =============================================================
    # SERVICE EXECUTION
    # =============================================================

    async def _execute_service_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        blocking: bool,
        target: Optional[dict[str, Any]] = None,
    ) -> None:
        """Execute and centrally log a Home Assistant service call."""
        try:
            await self.hass.services.async_call(
                domain,
                service,
                data,
                blocking=blocking,
                target=target,
            )
        except Exception:
            _LOGGER.exception(
                "Device %s: error calling %s.%s with data=%s target=%s",
                self.conf.device_id,
                domain,
                service,
                data,
                target,
            )

    async def call_service(
        self,
        service: str,
        data: dict[str, Any],
        *,
        domain: str,
        blocking: bool = False,
    ) -> None:
        """Call a service for every configured entity in a domain."""
        entities = self.entities_for_domain(domain)

        if not entities:
            _LOGGER.error(
                "Device %s: no entities configured for domain %s; cannot call %s.%s",
                self.conf.device_id,
                domain,
                domain,
                service,
            )
            return

        await self.call_service_for_entities(
            service,
            data,
            entities,
            domain=domain,
            blocking=blocking,
        )

    async def call_service_for_entities(
        self,
        service: str,
        data: dict[str, Any],
        entities: list[str],
        *,
        domain: str,
        blocking: bool = False,
    ) -> None:
        """Call a service for an explicit entity list, bypassing domain lookup."""
        if not entities:
            return

        service_data = dict(data)
        service_data["entity_id"] = entities

        await self._execute_service_call(
            domain,
            service,
            service_data,
            blocking=blocking,
        )

    # =============================================================
    # CONFIGURED ACTION EXECUTION
    # =============================================================

    async def execute_button_action(
        self,
        actions: list[dict[str, Any]],
        *,
        name: str = "pico_link_action",
    ) -> None:
        """
        Run a configured action sequence.

        Actions were already validated against Home Assistant's own
        script schema in config.py, so the full range of native
        actions is supported here: plain service calls, conditions,
        if-then, choose, repeat, and templates — executed with the
        same engine Home Assistant scripts and automations use.
        """
        if not actions:
            return

        script = self._script_for(actions, name)

        try:
            await script.async_run(context=Context())
        except Exception:
            _LOGGER.exception(
                "Device %s: error running configured action sequence",
                self.conf.device_id,
            )

    def _script_for(
        self,
        actions: list[dict[str, Any]],
        name: str,
    ) -> Script:
        """Return the cached Script for an action list, creating it on first use."""
        cached = self._scripts.get(id(actions))

        if cached is not None and cached[0] is actions:
            return cached[1]

        # Parallel mode so a repeat press arriving while a previous run
        # is still inside a delay: (or any slow step) starts a new run
        # instead of being refused as "Already running".
        script = Script(
            self.hass,
            actions,
            name,
            DOMAIN,
            logger=_LOGGER,
            running_description=f"Pico Link {name} for device {self.conf.device_id}",
            script_mode="parallel",
        )

        self._scripts[id(actions)] = (actions, script)

        return script

    async def async_unload_scripts(self) -> None:
        """Stop and release every cached Script; called from the controller's stop path."""
        scripts = [script for _, script in self._scripts.values()]
        self._scripts.clear()

        for script in scripts:
            await script.async_stop()

            # Script only deregisters itself from hass.data on
            # _async_unload(), which not every Home Assistant release
            # provides.
            unload = getattr(script, "_async_unload", None)

            if callable(unload):
                result = unload()

                if inspect.isawaitable(result):
                    await result
