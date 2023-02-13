"""GoodWe PV inverter selection settings entities."""
import logging

from goodwe import Inverter, InverterError, OperationMode

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, KEY_DEVICE_INFO, KEY_INVERTER

_LOGGER = logging.getLogger(__name__)


_MODE_TO_OPTION: dict[OperationMode, str] = {
    OperationMode.GENERAL: "general",
    OperationMode.OFF_GRID: "off_grid",
    OperationMode.BACKUP: "backup",
    OperationMode.ECO: "eco",
    OperationMode.PEAK_SHAVING: "peak_shaving",
    OperationMode.ECO_CHARGE: "eco_charge",
    OperationMode.ECO_DISCHARGE: "eco_discharge",
}

_OPTION_TO_MODE: dict[str, OperationMode] = {
    value: key for key, value in _MODE_TO_OPTION.items()
}

OPERATION_MODE = SelectEntityDescription(
    key="operation_mode",
    name="Inverter operation mode",
    icon="mdi:solar-power",
    entity_category=EntityCategory.CONFIG,
    translation_key="operation_mode",
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the inverter select entities from a config entry."""
    inverter = hass.data[DOMAIN][config_entry.entry_id][KEY_INVERTER]
    device_info = hass.data[DOMAIN][config_entry.entry_id][KEY_DEVICE_INFO]

    supported_modes = await inverter.get_operation_modes(True)
    # read current operating mode from the inverter
    try:
        active_mode = await inverter.get_operation_mode()
    except (InverterError, ValueError):
        # Inverter model does not support this setting
        _LOGGER.debug("Could not read inverter operation mode")
    else:
        active_power = None
        try:
            if active_mode:
                active_power = (await inverter.read_setting("eco_mode_1")).power
        except (InverterError, ValueError):
            _LOGGER.debug("Could not read inverter eco mode")
            active_power = 0

        entity = InverterOperationModeEntity(
            device_info,
            OPERATION_MODE,
            inverter,
            [v for k, v in _MODE_TO_OPTION.items() if k in supported_modes],
            _MODE_TO_OPTION[active_mode],
            active_power,
        )
        async_add_entities([entity])

        eco_mode_entity_id = entity_registry.async_get(hass).async_get_entity_id(
            Platform.NUMBER,
            DOMAIN,
            f"{DOMAIN}-eco_mode_power-{inverter.serial_number}",
        )
        if eco_mode_entity_id:
            async_track_state_change_event(
                hass,
                eco_mode_entity_id,
                entity.update_eco_mode_power,
            )


class InverterOperationModeEntity(SelectEntity):
    """Entity representing the inverter operation mode."""

    _attr_should_poll = False

    def __init__(
        self,
        device_info: DeviceInfo,
        description: SelectEntityDescription,
        inverter: Inverter,
        supported_options: list[str],
        current_mode: str,
        current_power: int,
    ) -> None:
        """Initialize the inverter operation mode setting entity."""
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}-{description.key}-{inverter.serial_number}"
        self._attr_device_info = device_info
        self._attr_options = supported_options
        self._attr_current_option = current_mode
        self._inverter: Inverter = inverter
        self._eco_mode_power = current_power

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self._inverter.set_operation_mode(
            _OPTION_TO_MODE[option], self._eco_mode_power
        )
        self._attr_current_option = option
        self.async_write_ha_state()

    async def update_eco_mode_power(self, event: Event) -> None:
        """Update eco mode power value in inverter (when in eco mode)"""
        self._eco_mode_power = int(float(event.data.get("new_state").state))
        if event.data.get("old_state"):
            operation_mode = _OPTION_TO_MODE(self.current_option)
            if operation_mode in (
                OperationMode.ECO_CHARGE,
                OperationMode.ECO_DISCHARGE,
            ):
                await self._inverter.set_operation_mode(
                    operation_mode, self._eco_mode_power
                )
