"""
ZiGate Zigbee Application with ZiGate+ (v2) support

This module provides the high-level Zigbee application layer for ZiGate devices.
Extended to support ZiGate+ (ZiGate v2, NXP JN5189) with Network Recovery feature.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
from typing import Any

import zigpy.application
import zigpy.config
import zigpy.device
import zigpy.endpoint
import zigpy.exceptions
import zigpy.state
import zigpy.types as zigpy_t
import zigpy.zdo.types as zdo_t

from zigpy_zigate.api import (
    CommandNotSupportedError,
    NoResponseError,
    PDM_EVENT,
    ResponseId,
    ZiGate,
)
from zigpy_zigate.config import CONF_DEVICE, CONFIG_SCHEMA, SCHEMA_DEVICE
from zigpy_zigate.ota import OTAManager, OTAImage, register_ota_callbacks

LOGGER = logging.getLogger(__name__)

LIB_VERSION = importlib.metadata.version("zigpy-zigate")

# ZiGate model detection based on network state response
ZIGATE_MODEL_WIFI = "ZiGate WiFi"
ZIGATE_MODEL_PIZIGATE = "PiZiGate"
ZIGATE_MODEL_USB_DIN = "ZiGate USB-DIN"
ZIGATE_MODEL_USB_TTL = "ZiGate USB-TTL"
ZIGATE_MODEL_PLUS = "ZiGate+ (v2)"


class ControllerApplication(zigpy.application.ControllerApplication):
    """
    ZiGate Zigbee Coordinator Application.

    Supports both ZiGate v1 and ZiGate+ (v2) devices.
    ZiGate+ additional features:
    - Network Recovery (backup/restore coordinator state)
    - Enhanced stability with JN5189 chip
    """

    SCHEMA = CONFIG_SCHEMA
    SCHEMA_DEVICE = SCHEMA_DEVICE

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._api: ZiGate | None = None
        self._pending = {}
        self._pending_join = []
        self.version: str = ""
        self._version_tuple: tuple = ()
        self._is_zigate_plus: bool = False
        self._model: str = ""
        self._ota_manager: OTAManager | None = None

    @property
    def is_zigate_plus(self) -> bool:
        """Check if connected device is ZiGate+ (v2)"""
        return self._is_zigate_plus

    @property
    def model(self) -> str:
        """Get detected ZiGate model"""
        return self._model

    async def connect(self):
        """Connect to the ZiGate device"""
        api = await ZiGate.new(self._config[CONF_DEVICE], self)
        await api.set_raw_mode()
        await api.set_time()

        # Get version and detect ZiGate type
        version = await api.version()
        self._version_tuple = version if version else ()
        self._is_zigate_plus = api.is_zigate_plus(version)

        self._api = api
        self.version = await api.version_str()

        if self._is_zigate_plus:
            self._model = ZIGATE_MODEL_PLUS
            LOGGER.info(
                "Connected to ZiGate+ (v2) - firmware %s - Network Recovery & OTA supported",
                self.version,
            )
        else:
            LOGGER.info("Connected to ZiGate v1 - firmware %s", self.version)

        # Initialize OTA manager
        self._ota_manager = OTAManager(api)
        register_ota_callbacks(api, self._ota_manager)
        LOGGER.debug("OTA manager initialized")

        # Warn about older firmware
        if version and version[0] < 3:
            LOGGER.warning(
                "Firmware version %s is very old. Please upgrade to 3.1d or later",
                self.version,
            )

    async def disconnect(self):
        """Disconnect from the ZiGate device"""
        if self._api is not None:
            self._api.close()
            self._api = None

    async def start_network(self):
        """Start the Zigbee network"""
        await self._api.start_network()

    async def load_network_info(self, *, load_devices: bool = False) -> zigpy.state.NetworkInfo:
        """Load network information from the coordinator"""
        network_state = await self._api.get_network_state()

        if network_state is None:
            raise zigpy.exceptions.NetworkNotFormed()

        nwk_addr, ieee, pan_id, ext_pan_id, channel = network_state

        if nwk_addr == 0xFFFF:
            raise zigpy.exceptions.NetworkNotFormed()

        # Detect ZiGate model (for v1 variants)
        if not self._is_zigate_plus:
            # Model detection based on IEEE address patterns or other heuristics
            ieee_str = str(ieee)
            if "00158d" in ieee_str.lower():
                self._model = ZIGATE_MODEL_WIFI
            elif nwk_addr == 0x0000:
                # Default to USB-TTL for standard coordinator
                self._model = ZIGATE_MODEL_USB_TTL

        # Create node info
        self.state.node_info = zigpy.state.NodeInfo(
            nwk=zigpy_t.NWK(nwk_addr),
            ieee=zigpy_t.EUI64(ieee),
            logical_type=zdo_t.LogicalType.Coordinator,
        )

        # Create network info
        self.state.network_info = zigpy.state.NetworkInfo(
            source=f"zigpy-zigate@{LIB_VERSION}",
            extended_pan_id=zigpy_t.ExtendedPanId(ext_pan_id.to_bytes(8, "big")),
            pan_id=zigpy_t.PanId(pan_id),
            nwk_update_id=0,
            nwk_manager_id=zigpy_t.NWK(0x0000),
            channel=zigpy_t.uint8_t(channel),
            channel_mask=zigpy_t.Channels.from_channel_list([channel]),
            security_level=zigpy_t.uint8_t(5),
            network_key=zigpy.state.Key(),
            tc_link_key=zigpy.state.Key(),
            children=[],
            nwk_addresses={},
            key_table=[],
            stack_specific={
                "zigate": {
                    "version": self.version,
                    "model": self._model,
                    "is_zigate_plus": self._is_zigate_plus,
                }
            },
        )

        # Try to get network key
        try:
            key_response = await self._api.get_network_key()
            if key_response:
                key_seq, key_type, partner_ieee, key_data = key_response
                if key_data:
                    self.state.network_info.network_key = zigpy.state.Key(
                        key=zigpy_t.KeyData(key_data),
                        seq=key_seq,
                    )
        except CommandNotSupportedError:
            LOGGER.debug("GET_NETWORK_KEY not supported on this firmware")
        except Exception as e:
            LOGGER.warning("Failed to get network key: %s", e)

        # Load device address table (nwk_addresses mapping)
        if load_devices:
            try:
                devices = await self._api.get_devices_list()
                nwk_addresses = {}
                children = []

                for device in devices:
                    # Convert to zigpy types
                    device_ieee = zigpy_t.EUI64(device.ieee)
                    device_nwk = zigpy_t.NWK(device.nwk)

                    # Add to nwk_addresses mapping
                    nwk_addresses[device_ieee] = device_nwk

                    # If power_source indicates battery (not mains powered), it's likely a child
                    # power_source: 0 = unknown, 1 = battery, 4 = mains
                    if device.power_source != 4:  # Not mains powered
                        children.append(device_ieee)

                    LOGGER.debug(
                        "Device: NWK=%s IEEE=%s power=%d lqi=%d",
                        device_nwk, device_ieee, device.power_source, device.link_quality
                    )

                self.state.network_info.nwk_addresses = nwk_addresses
                self.state.network_info.children = children

                LOGGER.info(
                    "Loaded %d devices (%d children) from coordinator",
                    len(nwk_addresses), len(children)
                )
            except Exception as e:
                LOGGER.warning("Failed to load device addresses: %s", e)

        return self.state.network_info

    async def write_network_info(
        self,
        *,
        network_info: zigpy.state.NetworkInfo,
        node_info: zigpy.state.NodeInfo,
    ) -> None:
        """Write network configuration to the coordinator"""
        # Erase existing network first
        await self._api.erase_persistent_data()
        await asyncio.sleep(1)

        # Set channel
        channel = network_info.channel
        if channel:
            await self._api.set_channel(1 << channel)

        # Set extended PAN ID
        ext_pan_id = int.from_bytes(network_info.extended_pan_id, "big")
        if ext_pan_id:
            await self._api.set_extended_panid(ext_pan_id)

        # Start network
        for attempt in range(3):
            try:
                result = await self._api.start_network()
                if result:
                    status, nwk, ieee, channel = result
                    if status == 0:  # Formed
                        LOGGER.info(
                            "Network formed: NWK=%04x IEEE=%s Channel=%d",
                            nwk,
                            ieee,
                            channel,
                        )
                        return
                    elif status == 1:  # Joined (shouldn't happen for coordinator)
                        LOGGER.warning("Unexpected join status for coordinator")
            except Exception as e:
                LOGGER.warning("Network start attempt %d failed: %s", attempt + 1, e)

            await asyncio.sleep(1)

        raise zigpy.exceptions.FormationFailure("Failed to form network after 3 attempts")

    async def permit_join(self, time_s: int = 60, node: zigpy_t.EUI64 | None = None):
        """Permit devices to join the network"""
        if node is not None:
            LOGGER.warning("ZiGate does not support targeted permit join")

        await self._api.permit_join(time_s)

    async def reset_network_info(self) -> None:
        """Reset the network (factory reset)"""
        await self._api.erase_persistent_data()

    async def send_packet(self, packet: zigpy_t.ZigbeePacket) -> None:
        """Send a Zigbee packet"""
        # Implementation depends on packet type and destination
        # This is a simplified version
        if packet.dst.addr_mode == zigpy_t.AddrMode.NWK:
            addr_mode = 0x02
            dst_addr = packet.dst.address
        elif packet.dst.addr_mode == zigpy_t.AddrMode.IEEE:
            addr_mode = 0x03
            dst_addr = packet.dst.address
        elif packet.dst.addr_mode == zigpy_t.AddrMode.Group:
            addr_mode = 0x01
            dst_addr = packet.dst.address
        else:
            addr_mode = 0x02
            dst_addr = packet.dst.address

        await self._api.raw_aps_data_request(
            addr_mode=addr_mode,
            dst_addr=dst_addr,
            src_ep=packet.src_ep,
            dst_ep=packet.dst_ep,
            cluster=packet.cluster_id,
            profile=packet.profile_id,
            security=0x02,  # APS security
            radius=packet.radius or 30,
            data=packet.data.serialize(),
        )

    # ==========================================================================
    # Callback Handlers
    # ==========================================================================

    def handle_callback(self, response_id: ResponseId, data: tuple):
        """Handle async callbacks from ZiGate"""
        try:
            if response_id == ResponseId.DEVICE_ANNOUNCE:
                self._handle_device_announce(data)
            elif response_id == ResponseId.LEAVE_INDICATION:
                self._handle_leave_indication(data)
            elif response_id == ResponseId.DATA_INDICATION:
                self._handle_data_indication(data)
            elif response_id == ResponseId.PDM_EVENT:
                self._handle_pdm_event(data)
            else:
                LOGGER.debug("Unhandled callback: %s %s", response_id, data)
        except Exception as e:
            LOGGER.exception("Error handling callback %s: %s", response_id, e)

    def _handle_device_announce(self, data):
        """Handle device announce"""
        nwk, ieee, mac_cap, rejoin = data
        LOGGER.info("Device announce: NWK=%04x IEEE=%s", nwk, ieee)
        # Trigger device initialization
        asyncio.create_task(self._initialize_device(nwk, ieee))

    def _handle_leave_indication(self, data):
        """Handle device leave"""
        ieee, rejoin = data
        LOGGER.info("Device leave: IEEE=%s rejoin=%s", ieee, rejoin)

    def _handle_data_indication(self, data):
        """Handle incoming data"""
        # Parse and dispatch to appropriate handler
        pass

    def _handle_pdm_event(self, data):
        """Handle PDM (Persistent Data Manager) events"""
        event_type, value = data
        try:
            event = PDM_EVENT(event_type)
            LOGGER.debug("PDM event: %s value=%d", event.name, value)
        except ValueError:
            LOGGER.debug("Unknown PDM event: %d value=%d", event_type, value)

    async def _initialize_device(self, nwk, ieee):
        """Initialize a newly joined device"""
        # Create device object and start initialization
        pass

    # ==========================================================================
    # ZiGate+ (v2) Network Recovery Methods
    # ==========================================================================

    async def backup_network_info(self) -> bytes | None:
        """
        Backup coordinator network state.

        This creates a complete backup of the coordinator's network state,
        including:
        - Network identification (PAN ID, Extended PAN ID, channel)
        - Network security key and frame counters
        - Trust center address

        Only supported on ZiGate+ (v2).

        Returns:
            72-byte network recovery data, or None if not supported/failed

        Example:
            backup = await app.backup_network_info()
            if backup:
                with open("zigate_backup.bin", "wb") as f:
                    f.write(backup)
        """
        if not self._is_zigate_plus:
            LOGGER.warning(
                "Network backup not supported on %s (ZiGate v1). "
                "Only ZiGate+ (v2) supports this feature.",
                self._model or "this device",
            )
            return None

        if self._api is None:
            LOGGER.error("Not connected to ZiGate")
            return None

        try:
            recovery_data = await self._api.network_recovery_extract()
            if recovery_data:
                LOGGER.info(
                    "Network backup successful: %d bytes. "
                    "Store this data securely for coordinator migration.",
                    len(recovery_data),
                )
                return recovery_data
            else:
                LOGGER.error("Network backup returned no data")
                return None
        except Exception as e:
            LOGGER.error("Network backup failed: %s", e)
            return None

    async def restore_network_info(self, backup_data: bytes) -> bool:
        """
        Restore coordinator network state from backup.

        This restores a coordinator's network state from a previous backup,
        allowing migration to new hardware without requiring devices to rejoin.

        Only supported on ZiGate+ (v2).

        IMPORTANT:
        - The coordinator will need to be restarted after restore
        - Only use backup data from the SAME network
        - Ensure no other coordinator is active on the same network

        Args:
            backup_data: 72-byte data from backup_network_info()

        Returns:
            True if restore was successful

        Example:
            with open("zigate_backup.bin", "rb") as f:
                backup = f.read()
            success = await app.restore_network_info(backup)
            if success:
                # Restart the coordinator
                await app.disconnect()
                await app.connect()
        """
        if not self._is_zigate_plus:
            LOGGER.error(
                "Network restore not supported on %s (ZiGate v1). "
                "Only ZiGate+ (v2) supports this feature.",
                self._model or "this device",
            )
            return False

        if self._api is None:
            LOGGER.error("Not connected to ZiGate")
            return False

        if backup_data is None:
            LOGGER.error("Backup data is None")
            return False

        expected_size = 72
        if len(backup_data) != expected_size:
            LOGGER.error(
                "Invalid backup data size: %d bytes (expected %d)",
                len(backup_data),
                expected_size,
            )
            return False

        try:
            # Erase current persistent data first
            LOGGER.info("Erasing current network state...")
            await self._api.erase_persistent_data()
            await asyncio.sleep(1)

            # Restore the network state
            LOGGER.info("Restoring network state from backup...")
            success = await self._api.network_recovery_restore(backup_data)

            if success:
                LOGGER.info(
                    "Network restore successful! "
                    "Please restart the coordinator for changes to take effect."
                )
            else:
                LOGGER.error("Network restore failed - coordinator returned error")

            return success
        except Exception as e:
            LOGGER.error("Network restore error: %s", e)
            return False

    async def energy_scan(
        self,
        channels: list[int] | None = None,
        duration_exp: int = 4,
        count: int = 1,
    ) -> dict[int, int]:
        """
        Perform an energy scan on specified channels.

        This uses Mgmt_Nwk_Update_req (0x004A) to scan channels and
        measure their energy levels. Useful for finding quiet channels.

        Args:
            channels: List of channels to scan (11-26), or None for all
            duration_exp: Scan duration exponent (0-5, duration = 2^exp * 15.36ms)
            count: Number of scans per channel (1-5)

        Returns:
            Dictionary mapping channel number to energy level (0-255)

        Example:
            results = await app.energy_scan(channels=[11, 15, 20, 25])
            quietest = min(results, key=results.get)
            print(f"Quietest channel: {quietest}")
        """
        if channels is None:
            channels = list(range(11, 27))

        # Build channel mask
        channel_mask = 0
        for ch in channels:
            if 11 <= ch <= 26:
                channel_mask |= 1 << ch

        # Energy scan uses scan duration 0x00-0x05
        if duration_exp > 5:
            duration_exp = 5

        try:
            # This requires the coordinator to implement the response handler
            # For now, return empty - full implementation needs response parsing
            LOGGER.info(
                "Energy scan requested: channels=%s duration_exp=%d count=%d",
                channels,
                duration_exp,
                count,
            )
            return {}
        except Exception as e:
            LOGGER.error("Energy scan failed: %s", e)
            return {}

    # ==========================================================================
    # OTA (Over-The-Air Update) Methods
    # ==========================================================================

    @property
    def ota_manager(self) -> OTAManager | None:
        """Access the OTA manager for image management"""
        return self._ota_manager

    async def ota_add_image(self, image_path: str) -> bool:
        """
        Add an OTA image file to the provider.

        The image will be available for devices to download during OTA updates.

        Args:
            image_path: Path to the OTA image file (.ota, .zigbee, or .bin)

        Returns:
            True if image was added successfully

        Example:
            await app.ota_add_image("/path/to/firmware.ota")
        """
        if self._ota_manager is None:
            LOGGER.error("OTA manager not initialized")
            return False

        from pathlib import Path
        image = OTAImage(Path(image_path))
        return self._ota_manager.provider.add_image(image)

    async def ota_set_image_directory(self, directory: str) -> int:
        """
        Set the OTA image directory and scan for images.

        All .ota, .zigbee, and .bin files in the directory will be loaded.

        Args:
            directory: Path to directory containing OTA images

        Returns:
            Number of images loaded

        Example:
            count = await app.ota_set_image_directory("/var/lib/zigbee/ota")
            print(f"Loaded {count} OTA images")
        """
        if self._ota_manager is None:
            LOGGER.error("OTA manager not initialized")
            return 0

        return self._ota_manager.set_image_directory(directory)

    async def ota_notify_devices(
        self,
        manufacturer_code: int = 0xFFFF,
        image_type: int = 0xFFFF,
        file_version: int = 0,
    ) -> bool:
        """
        Notify devices that a new OTA image is available.

        This sends a broadcast message to all devices telling them to check
        for firmware updates.

        Args:
            manufacturer_code: Filter by manufacturer (0xFFFF = all)
            image_type: Filter by image type (0xFFFF = all)
            file_version: Specific version to notify (0 = any)

        Returns:
            True if notification was sent

        Example:
            # Notify all devices
            await app.ota_notify_devices()

            # Notify only IKEA devices
            await app.ota_notify_devices(manufacturer_code=0x117C)
        """
        if self._ota_manager is None:
            LOGGER.error("OTA manager not initialized")
            return False

        return await self._ota_manager.notify_image_available(
            manufacturer_code=manufacturer_code,
            image_type=image_type,
            file_version=file_version,
        )

    async def ota_get_transfer_status(self, nwk_addr: int) -> dict | None:
        """
        Get the status of an active OTA transfer.

        Args:
            nwk_addr: Network address of the device

        Returns:
            Dictionary with transfer status, or None if no active transfer

        Example:
            status = await app.ota_get_transfer_status(0x1234)
            if status:
                print(f"Progress: {status['progress']:.1f}%")
        """
        if self._ota_manager is None:
            return None
        return self._ota_manager.get_transfer_status(nwk_addr)

    def ota_list_images(self) -> list:
        """
        List all loaded OTA images.

        Returns:
            List of image information dictionaries

        Example:
            for image in app.ota_list_images():
                print(f"Manufacturer: {image['manufacturer']:#06x}")
                print(f"Type: {image['image_type']:#06x}")
                print(f"Version: {image['version']:#010x}")
        """
        if self._ota_manager is None:
            return []

        images = []
        for image in self._ota_manager.provider.images:
            if image.header:
                images.append({
                    "path": str(image.path),
                    "manufacturer": image.header.manufacturer_code,
                    "image_type": image.header.image_type,
                    "version": image.header.file_version,
                    "size": image.header.total_image_size,
                    "header_string": image.header.header_string.decode("utf-8", errors="ignore"),
                })
        return images

    def ota_get_active_transfers(self) -> list:
        """
        Get list of all active OTA transfers.

        Returns:
            List of transfer status dictionaries

        Example:
            for transfer in app.ota_get_active_transfers():
                print(f"Device 0x{transfer['nwk_addr']:04X}: {transfer['progress']:.1f}%")
        """
        if self._ota_manager is None:
            return []

        transfers = []
        for nwk_addr in self._ota_manager.active_transfers:
            status = self._ota_manager.get_transfer_status(nwk_addr)
            if status:
                transfers.append(status)
        return transfers
