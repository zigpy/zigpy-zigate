"""
ZiGate API module with ZiGate+ (v2) support

This module provides the low-level API for communicating with ZiGate devices.
Extended to support ZiGate+ (ZiGate v2, NXP JN5189) with Network Recovery feature.
"""

from __future__ import annotations

import asyncio
import binascii
import enum
import functools
import logging
import sys
from typing import Any

import async_timeout
import serial
import serial_asyncio

from zigpy_zigate import types as t

LOGGER = logging.getLogger(__name__)

COMMAND_TIMEOUT = 6.0
RESPONSE_TIMEOUT = 6.0
PROBE_TIMEOUT = 3.0

# ZiGate+ Network Recovery data size
NETWORK_RECOVERY_SIZE = 72


class CommandNotSupportedError(Exception):
    pass


class NoResponseError(Exception):
    pass


class PDM_EVENT(enum.IntEnum):
    E_PDM_SYSTEM_EVENT_WEAR_COUNT_TRIGGER_VALUE_REACHED = 0
    E_PDM_SYSTEM_EVENT_DESCRIPTOR_SAVE_FAILED = 1
    E_PDM_SYSTEM_EVENT_PDM_NOT_ENOUGH_SPACE = 2
    E_PDM_SYSTEM_EVENT_LARGEST_RECORD_FULL_SAVE_NO_LONGER_POSSIBLE = 3
    E_PDM_SYSTEM_EVENT_SEGMENT_DATA_CHECKSUM_FAIL = 4
    E_PDM_SYSTEM_EVENT_SEGMENT_SAVE_OK = 5
    E_PDM_SYSTEM_EVENT_EEPROM_SEGMENT_HEADER_REPAIRED = 6
    E_PDM_SYSTEM_EVENT_SYSTEM_INTERNAL_BUFFER_WEAR_COUNT_SWAP = 7
    E_PDM_SYSTEM_EVENT_SYSTEM_DUPLICATE_FILE_SEGMENT_DETECTED = 8
    E_PDM_SYSTEM_EVENT_SYSTEM_ERROR = 9
    E_PDM_SYSTEM_EVENT_SEGMENT_PREWRITE = 10
    E_PDM_SYSTEM_EVENT_SEGMENT_POSTWRITE = 11
    E_PDM_SYSTEM_EVENT_SEQUENCE_DUPLICATE_DETECTED = 12
    E_PDM_SYSTEM_EVENT_SEQUENCE_VERIFY_FAIL = 13
    E_PDM_SYSTEM_EVENT_PDM_SMART_SAVE = 14
    E_PDM_SYSTEM_EVENT_PDM_FULL_SAVE = 15


class CommandId(enum.IntEnum):
    SET_RAWMODE = 0x0002
    SET_TIMESERVER = 0x0016
    GET_DEVICES_LIST = 0x0015
    SET_LED = 0x0018
    SET_CERTIFICATION = 0x0019
    SET_CHANNEL_MASK = 0x0021
    SET_EXTENDED_PANID = 0x0020
    NETWORK_STATE_REQ = 0x0009
    GET_VERSION = 0x0010
    RESET = 0x0011
    ERASE_PERSISTENT_DATA = 0x0012
    PERMIT_JOIN = 0x0049
    MANAGEMENT_NETWORK_UPDATE_REQUEST = 0x004A
    START_NETWORK = 0x0024
    REMOVE_DEVICE = 0x0026
    GET_NETWORK_KEY = 0x0027
    # OTA (Over-The-Air Update) commands
    OTA_LOAD_NEW_IMAGE = 0x0500       # Upload OTA image header to coordinator
    OTA_BLOCK_SEND = 0x0502           # Send image block to requesting device
    OTA_UPGRADE_END_RESPONSE = 0x0504 # Confirm upgrade completion
    OTA_IMAGE_NOTIFY = 0x0505         # Notify devices of available image
    OTA_SEND_WAIT_FOR_DATA = 0x0506   # Tell device to wait before next block
    SEND_RAW_APS_DATA_PACKET = 0x0530
    # ZiGate+ (v2) Network Recovery commands
    NETWORK_RECOVERY_EXTRACT = 0x0600
    NETWORK_RECOVERY_RESTORE = 0x0601
    NETWORK_RECOVERY_EXTRACT_EXT = 0x0602  # Extended with device table
    NETWORK_RECOVERY_RESTORE_EXT = 0x0603  # Extended with device table


class ResponseId(enum.IntEnum):
    DEVICE_ANNOUNCE = 0x004D
    STATUS = 0x8000
    LOG = 0x8001
    DATA_INDICATION = 0x8002
    NETWORK_STATE_RSP = 0x8009
    VERSION_LIST = 0x8010
    ACK_DATA = 0x8011
    APS_DATA_CONFIRM = 0x8012
    GET_DEVICES_LIST = 0x8015
    PERMIT_JOIN_RSP = 0x8049
    MANAGEMENT_NETWORK_UPDATE_RSP = 0x804A
    NETWORK_JOINED_FORMED = 0x8024
    LEAVE_INDICATION = 0x8048
    PDM_EVENT = 0x8035
    PDM_LOADED = 0x0302
    NODE_NON_FACTORY_NEW_RESTART = 0x8006
    NODE_FACTORY_NEW_RESTART = 0x8007
    GET_NETWORK_KEY = 0x8027
    # OTA (Over-The-Air Update) responses
    OTA_BLOCK_REQUEST = 0x8501        # Device requests image block
    OTA_UPGRADE_END_REQUEST = 0x8503  # Device finished download, ready to upgrade
    # ZiGate+ (v2) Network Recovery responses
    NETWORK_RECOVERY_EXTRACT_RSP = 0x8600
    NETWORK_RECOVERY_RESTORE_RSP = 0x8601
    NETWORK_RECOVERY_EXTRACT_EXT_RSP = 0x8602  # Extended with device table
    NETWORK_RECOVERY_RESTORE_EXT_RSP = 0x8603  # Extended with device table


class SendSecurity(enum.IntEnum):
    NETWORK = 0x01
    APPLINK = 0x02
    TEMP_APPLINK = 0x04


# Response data type mappings
RESPONSES = {
    ResponseId.DEVICE_ANNOUNCE: (t.NWK, t.EUI64, t.uint8_t, t.uint8_t),
    ResponseId.STATUS: (
        t.uint8_t,
        t.uint8_t,
        t.uint16_t,
        t.uint8_t,
        t.uint8_t,
        t.uint8_t,
        t.uint8_t,
    ),
    ResponseId.LOG: (t.LogLevel, t.LBytes),
    ResponseId.DATA_INDICATION: (
        t.uint8_t,
        t.uint16_t,
        t.uint16_t,
        t.uint8_t,
        t.uint8_t,
        t.uint8_t,
        t.uint8_t,
        t.uint16_t,
        t.Address,
        t.Address,
        t.LBytes,
    ),
    ResponseId.NETWORK_STATE_RSP: (t.NWK, t.EUI64, t.uint16_t, t.uint64_t, t.uint8_t),
    ResponseId.VERSION_LIST: (t.uint16_t, t.uint16_t),
    ResponseId.ACK_DATA: (t.uint8_t, t.uint8_t, t.NWK, t.uint8_t),
    ResponseId.APS_DATA_CONFIRM: (
        t.uint8_t,
        t.uint8_t,
        t.uint8_t,
        t.Address,
        t.uint8_t,
    ),
    ResponseId.GET_DEVICES_LIST: (t.DeviceEntryArray,),
    ResponseId.PERMIT_JOIN_RSP: (t.uint8_t,),
    ResponseId.MANAGEMENT_NETWORK_UPDATE_RSP: (
        t.NWK,
        t.uint8_t,
        t.uint8_t,
        t.uint8_t,
        t.uint16_t,
        t.LBytes,
    ),
    ResponseId.NETWORK_JOINED_FORMED: (
        t.uint8_t,
        t.NWK,
        t.EUI64,
        t.uint8_t,
    ),
    ResponseId.LEAVE_INDICATION: (t.EUI64, t.uint8_t),
    ResponseId.PDM_EVENT: (t.uint8_t, t.uint32_t),
    ResponseId.PDM_LOADED: (),
    ResponseId.NODE_NON_FACTORY_NEW_RESTART: (t.uint8_t,),
    ResponseId.NODE_FACTORY_NEW_RESTART: (t.uint8_t,),
    ResponseId.GET_NETWORK_KEY: (
        t.uint8_t,
        t.uint8_t,
        t.EUI64,
        t.Bytes,  # 16-byte key
    ),
    # OTA (Over-The-Air Update) responses
    ResponseId.OTA_BLOCK_REQUEST: (
        t.uint8_t,   # u8SrcEndPoint
        t.uint16_t,  # u16ClusterId
        t.uint8_t,   # u8AddrMode
        t.Address,   # u64Address (NWK or IEEE based on mode)
        t.uint32_t,  # u32FileOffset
        t.uint32_t,  # u32FileVersion
        t.uint16_t,  # u16ImageType
        t.uint16_t,  # u16ManufacturerCode
        t.uint16_t,  # u16BlockRequestDelay
        t.uint8_t,   # u8MaxDataSize
        t.uint8_t,   # u8FieldControl
    ),
    ResponseId.OTA_UPGRADE_END_REQUEST: (
        t.uint8_t,   # u8SrcEndPoint
        t.uint16_t,  # u16ClusterId
        t.uint8_t,   # u8AddrMode
        t.Address,   # u64Address
        t.uint32_t,  # u32FileVersion
        t.uint16_t,  # u16ImageType
        t.uint16_t,  # u16ManufacturerCode
        t.uint8_t,   # u8Status
    ),
    # ZiGate+ (v2) Network Recovery responses
    ResponseId.NETWORK_RECOVERY_EXTRACT_RSP: (t.Bytes,),  # 72-byte structure
    ResponseId.NETWORK_RECOVERY_RESTORE_RSP: (t.uint8_t,),  # Success flag
    ResponseId.NETWORK_RECOVERY_EXTRACT_EXT_RSP: (t.Bytes,),  # Extended with device table
    ResponseId.NETWORK_RECOVERY_RESTORE_EXT_RSP: (t.uint8_t,),  # Success flag
}

# Command parameter type mappings
COMMANDS = {
    CommandId.SET_RAWMODE: (t.uint8_t,),
    CommandId.SET_TIMESERVER: (t.uint32_t,),
    CommandId.GET_DEVICES_LIST: (),
    CommandId.SET_LED: (t.uint8_t,),
    CommandId.SET_CERTIFICATION: (t.uint8_t,),
    CommandId.SET_CHANNEL_MASK: (t.uint32_t,),
    CommandId.SET_EXTENDED_PANID: (t.uint64_t,),
    CommandId.NETWORK_STATE_REQ: (),
    CommandId.GET_VERSION: (),
    CommandId.RESET: (),
    CommandId.ERASE_PERSISTENT_DATA: (),
    CommandId.PERMIT_JOIN: (t.NWK, t.uint8_t, t.uint8_t),
    CommandId.MANAGEMENT_NETWORK_UPDATE_REQUEST: (
        t.NWK,
        t.uint32_t,
        t.uint8_t,
        t.uint8_t,
        t.uint8_t,
        t.uint16_t,
    ),
    CommandId.START_NETWORK: (),
    CommandId.REMOVE_DEVICE: (t.NWK, t.EUI64, t.EUI64),
    CommandId.GET_NETWORK_KEY: (),
    CommandId.SEND_RAW_APS_DATA_PACKET: (
        t.uint8_t,  # address mode
        t.Address,  # destination
        t.uint8_t,  # src ep
        t.uint8_t,  # dst ep
        t.uint16_t,  # cluster
        t.uint16_t,  # profile
        t.uint8_t,  # security mode
        t.uint8_t,  # radius
        t.LBytes,  # data
    ),
    # OTA (Over-The-Air Update) commands
    CommandId.OTA_LOAD_NEW_IMAGE: (
        t.uint8_t,   # u8AddressMode
        t.Address,   # u64Address (for unicast image notification)
        t.uint32_t,  # u32FileIdentifier (0x0BEEF11E for standard OTA)
        t.uint16_t,  # u16HeaderVersion
        t.uint16_t,  # u16HeaderLength
        t.uint16_t,  # u16HeaderControlField
        t.uint16_t,  # u16ManufacturerCode
        t.uint16_t,  # u16ImageType
        t.uint32_t,  # u32FileVersion
        t.uint16_t,  # u16StackVersion
        t.Bytes,     # au8HeaderString (32 bytes)
        t.uint32_t,  # u32TotalImage (total image size)
        t.uint8_t,   # u8SecurityCredVersion
        t.uint64_t,  # u64UpgradeFileDest
        t.uint16_t,  # u16MinimumHwVersion
        t.uint16_t,  # u16MaxHwVersion
    ),
    CommandId.OTA_BLOCK_SEND: (
        t.uint8_t,   # u8SrcEndPoint
        t.uint8_t,   # u8DstEndPoint
        t.uint16_t,  # u16DstAddress (NWK address)
        t.uint8_t,   # u8AddrMode
        t.uint8_t,   # u8SequenceNo
        t.uint8_t,   # u8Status (0=success)
        t.uint32_t,  # u32FileOffset
        t.uint32_t,  # u32FileVersion
        t.uint16_t,  # u16ImageType
        t.uint16_t,  # u16ManufacturerCode
        t.LBytes,    # Data block (up to 64 bytes)
    ),
    CommandId.OTA_UPGRADE_END_RESPONSE: (
        t.uint8_t,   # u8SrcEndPoint
        t.uint8_t,   # u8DstEndPoint
        t.uint16_t,  # u16DstAddress (NWK address)
        t.uint8_t,   # u8AddrMode
        t.uint8_t,   # u8SequenceNo
        t.uint32_t,  # u32UpgradeTime
        t.uint32_t,  # u32CurrentTime
        t.uint32_t,  # u32FileVersion
        t.uint16_t,  # u16ImageType
        t.uint16_t,  # u16ManufacturerCode
    ),
    CommandId.OTA_IMAGE_NOTIFY: (
        t.uint8_t,   # u8AddressMode (0x02=NWK, 0x04=broadcast)
        t.Address,   # u16Address (NWK address or broadcast 0xFFFF)
        t.uint8_t,   # u8SrcEndPoint
        t.uint8_t,   # u8DstEndPoint
        t.uint8_t,   # u8PayloadType (0-3, controls which fields are included)
        t.uint32_t,  # u32FileVersion
        t.uint16_t,  # u16ImageType
        t.uint16_t,  # u16ManufacturerCode
        t.uint8_t,   # u8QueryJitter (0-100)
    ),
    CommandId.OTA_SEND_WAIT_FOR_DATA: (
        t.uint8_t,   # u8SrcEndPoint
        t.uint8_t,   # u8DstEndPoint
        t.uint16_t,  # u16DstAddress (NWK address)
        t.uint8_t,   # u8AddrMode
        t.uint32_t,  # u32CurrentTime
        t.uint32_t,  # u32RequestTime
        t.uint16_t,  # u16BlockRequestDelayMs
    ),
    # ZiGate+ (v2) Network Recovery commands
    CommandId.NETWORK_RECOVERY_EXTRACT: (),  # No parameters
    CommandId.NETWORK_RECOVERY_RESTORE: (t.Bytes,),  # 72-byte recovery data
    CommandId.NETWORK_RECOVERY_EXTRACT_EXT: (),  # No parameters
    CommandId.NETWORK_RECOVERY_RESTORE_EXT: (t.Bytes,),  # Extended recovery data with devices
}


class PriorityLock:
    """Async lock with priority support for command ordering"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._priority_event = asyncio.Event()
        self._priority_event.set()
        self._high_priority = False

    async def acquire(self, high_priority: bool = False):
        if high_priority:
            self._high_priority = True
            self._priority_event.clear()
        else:
            await self._priority_event.wait()
        await self._lock.acquire()

    def release(self):
        if self._high_priority:
            self._high_priority = False
            self._priority_event.set()
        self._lock.release()


class ZiGate(asyncio.Protocol):
    """
    ZiGate protocol handler.

    Supports both ZiGate v1 and ZiGate+ (v2) devices.
    ZiGate+ features:
    - Network Recovery (backup/restore coordinator state)
    - Version >= 5.0
    """

    def __init__(self, api, on_transport_close=None):
        self._api = api
        self._transport = None
        self._buffer = b""
        self._status_waiters = {}
        self._response_waiters = {}
        self._lock = PriorityLock()
        self._on_transport_close = on_transport_close
        self._closing = False
        self._conn_lost_event = asyncio.Event()

    @classmethod
    async def new(cls, config, api=None, on_transport_close=None):
        loop = asyncio.get_event_loop()
        port = config.get("path")
        baudrate = config.get("baudrate", 115200)

        LOGGER.debug("Connecting to %s at %s baud", port, baudrate)

        _, protocol = await serial_asyncio.create_serial_connection(
            loop,
            functools.partial(cls, api, on_transport_close),
            port,
            baudrate=baudrate,
        )

        return protocol

    def close(self):
        self._closing = True
        if self._transport:
            self._transport.close()

    def connection_made(self, transport):
        LOGGER.debug("Connection established")
        self._transport = transport

    def connection_lost(self, exc):
        LOGGER.debug("Connection lost: %s", exc)
        self._conn_lost_event.set()
        if self._on_transport_close:
            self._on_transport_close()

    def data_received(self, data):
        self._buffer += data
        while self._buffer:
            frame, self._buffer = self._extract_frame(self._buffer)
            if frame is None:
                break
            self._handle_frame(frame)

    def _extract_frame(self, data):
        """Extract a complete frame from the buffer"""
        if len(data) < 5:
            return None, data

        # Find start byte
        start = data.find(b"\x01")
        if start == -1:
            return None, b""
        if start > 0:
            LOGGER.warning("Discarding %d bytes before start", start)
            data = data[start:]

        # Find end byte
        end = data.find(b"\x03", 1)
        if end == -1:
            return None, data

        frame = data[1:end]
        remaining = data[end + 1 :]

        # Unescape frame using ZiGate XOR 0x10 protocol
        # Bytes < 0x10 are escaped as: 0x02 + (byte XOR 0x10)
        # Example: 0x00 -> 0x02 0x10, 0x01 -> 0x02 0x11, etc.
        frame = self._unescape_data(frame)

        return frame, remaining

    def _unescape_data(self, data: bytes) -> bytes:
        """
        Unescape data according to ZiGate protocol.

        ZiGate escapes bytes < 0x10 as: 0x02 + (byte XOR 0x10)
        Example: 0x00 -> 0x02 0x10, 0x01 -> 0x02 0x11, etc.
        """
        result = b""
        i = 0
        while i < len(data):
            if data[i] == 0x02 and i + 1 < len(data):
                # Escaped byte: XOR with 0x10 to get original
                result += bytes([data[i + 1] ^ 0x10])
                i += 2
            else:
                result += bytes([data[i]])
                i += 1
        return result

    def _handle_frame(self, frame):
        """Process a received frame"""
        if len(frame) < 5:
            LOGGER.warning("Frame too short: %s", binascii.hexlify(frame))
            return

        msg_type = int.from_bytes(frame[0:2], "big")
        length = int.from_bytes(frame[2:4], "big")
        checksum = frame[4]
        data = frame[5 : 5 + length]

        # Verify checksum
        calc_checksum = 0
        for b in frame[0:4]:
            calc_checksum ^= b
        for b in data:
            calc_checksum ^= b

        if calc_checksum != checksum:
            LOGGER.warning("Checksum mismatch: got %02x, expected %02x", checksum, calc_checksum)
            return

        LOGGER.debug("Received: type=%04x data=%s", msg_type, binascii.hexlify(data))

        # Handle status responses
        if msg_type == ResponseId.STATUS:
            self._handle_status(data)
            return

        # Handle other responses
        try:
            response_id = ResponseId(msg_type)
        except ValueError:
            LOGGER.debug("Unknown response type: %04x", msg_type)
            return

        # Parse response data
        parsed = self._parse_response(response_id, data)

        # Notify waiters
        if response_id in self._response_waiters:
            waiter = self._response_waiters.pop(response_id)
            if not waiter.done():
                waiter.set_result(parsed)
        elif self._api:
            self._api.handle_callback(response_id, parsed)

    def _handle_status(self, data):
        """Handle status response"""
        if len(data) < 5:
            return

        status = data[0]
        seq_num = data[1]
        cmd_type = int.from_bytes(data[2:4], "big")

        LOGGER.debug("Status: status=%02x seq=%02x cmd=%04x", status, seq_num, cmd_type)

        if cmd_type in self._status_waiters:
            waiter = self._status_waiters.pop(cmd_type)
            if not waiter.done():
                waiter.set_result(status)

    def _parse_response(self, response_id, data):
        """Parse response data according to type definitions"""
        if response_id not in RESPONSES:
            return (data,)

        types = RESPONSES[response_id]
        result = []
        offset = 0

        for dtype in types:
            if offset >= len(data):
                break
            value, consumed = dtype.deserialize(data[offset:])
            result.append(value)
            offset += consumed

        return tuple(result)

    def _build_frame(self, msg_type, data):
        """Build a frame for transmission"""
        frame = msg_type.to_bytes(2, "big")
        frame += len(data).to_bytes(2, "big")

        # Calculate checksum
        checksum = 0
        for b in frame:
            checksum ^= b
        for b in data:
            checksum ^= b

        frame += bytes([checksum])
        frame += data

        # Escape special bytes using ZiGate XOR 0x10 protocol
        escaped = self._escape_data(frame)

        return b"\x01" + escaped + b"\x03"

    def _escape_data(self, data: bytes) -> bytes:
        """
        Escape data according to ZiGate protocol.

        ZiGate escapes bytes < 0x10 as: 0x02 + (byte XOR 0x10)
        Example: 0x00 -> 0x02 0x10, 0x01 -> 0x02 0x11, etc.
        """
        result = b""
        for b in data:
            if b < 0x10:
                # Escape: 0x02 followed by (byte XOR 0x10)
                result += bytes([0x02, b ^ 0x10])
            else:
                result += bytes([b])
        return result

    async def command(self, cmd, *args, wait_response=None):
        """Send a command and optionally wait for response"""
        if cmd not in COMMANDS:
            raise CommandNotSupportedError(f"Unknown command: {cmd}")

        # Serialize parameters
        types = COMMANDS[cmd]
        data = b""
        for dtype, arg in zip(types, args):
            if dtype == t.Bytes:
                data += arg
            else:
                data += dtype(arg).serialize()

        frame = self._build_frame(cmd, data)

        await self._lock.acquire()
        try:
            # Set up waiters
            status_waiter = asyncio.get_event_loop().create_future()
            self._status_waiters[cmd] = status_waiter

            response_waiter = None
            if wait_response:
                response_waiter = asyncio.get_event_loop().create_future()
                self._response_waiters[wait_response] = response_waiter

            LOGGER.debug("Sending: cmd=%04x data=%s", cmd, binascii.hexlify(data))
            self._transport.write(frame)

            # Wait for status
            async with async_timeout.timeout(COMMAND_TIMEOUT):
                status = await status_waiter

            if status != 0:
                LOGGER.warning("Command %04x returned status %02x", cmd, status)

            # Wait for response if requested
            if response_waiter:
                async with async_timeout.timeout(RESPONSE_TIMEOUT):
                    return await response_waiter

            return None

        finally:
            self._lock.release()
            self._status_waiters.pop(cmd, None)
            if wait_response:
                self._response_waiters.pop(wait_response, None)

    # ==========================================================================
    # API Methods
    # ==========================================================================

    async def version(self):
        """Get firmware version"""
        return await self.command(CommandId.GET_VERSION, wait_response=ResponseId.VERSION_LIST)

    async def version_str(self):
        """Get firmware version as string"""
        version = await self.version()
        if version:
            major = version[0]
            minor = version[1]
            return f"{major}.{minor:x}"
        return "unknown"

    async def reset(self):
        """Reset the ZiGate"""
        return await self.command(CommandId.RESET)

    async def set_raw_mode(self, mode=1):
        """Set raw mode for zigpy communication"""
        return await self.command(CommandId.SET_RAWMODE, mode)

    async def set_time(self, timestamp=None):
        """Set time server"""
        import time
        if timestamp is None:
            # Zigbee epoch is 2000-01-01
            timestamp = int(time.time()) - 946684800
        return await self.command(CommandId.SET_TIMESERVER, timestamp)

    async def set_led(self, enable=True):
        """Enable or disable LED"""
        return await self.command(CommandId.SET_LED, 1 if enable else 0)

    async def set_channel(self, channel_mask):
        """Set channel mask"""
        return await self.command(CommandId.SET_CHANNEL_MASK, channel_mask)

    async def set_extended_panid(self, extended_panid):
        """Set extended PAN ID"""
        return await self.command(CommandId.SET_EXTENDED_PANID, extended_panid)

    async def get_network_state(self):
        """Get current network state"""
        return await self.command(
            CommandId.NETWORK_STATE_REQ, wait_response=ResponseId.NETWORK_STATE_RSP
        )

    async def permit_join(self, duration=60, target=0xFFFC):
        """
        Allow devices to join the network.

        Args:
            duration: Permit join duration in seconds (0-254, or 255 for permanent)
            target: Target address for permit join request
                   - 0x0000: Local coordinator only
                   - 0xFFFC: Broadcast to all routers (standard Zigbee behavior)
        """
        return await self.command(
            CommandId.PERMIT_JOIN,
            target,
            duration,
            0,  # TC significance
            wait_response=ResponseId.PERMIT_JOIN_RSP,
        )

    async def start_network(self):
        """Start the Zigbee network"""
        return await self.command(
            CommandId.START_NETWORK, wait_response=ResponseId.NETWORK_JOINED_FORMED
        )

    async def erase_persistent_data(self):
        """Erase all persistent data (factory reset)"""
        return await self.command(CommandId.ERASE_PERSISTENT_DATA)

    async def remove_device(self, target_nwk, parent_ieee, child_ieee):
        """Remove a device from the network"""
        return await self.command(CommandId.REMOVE_DEVICE, target_nwk, parent_ieee, child_ieee)

    async def get_network_key(self):
        """Get the network encryption key"""
        return await self.command(
            CommandId.GET_NETWORK_KEY, wait_response=ResponseId.GET_NETWORK_KEY
        )

    async def raw_aps_data_request(
        self,
        addr_mode,
        dst_addr,
        src_ep,
        dst_ep,
        cluster,
        profile,
        security,
        radius,
        data,
    ):
        """Send raw APS data packet"""
        return await self.command(
            CommandId.SEND_RAW_APS_DATA_PACKET,
            addr_mode,
            dst_addr,
            src_ep,
            dst_ep,
            cluster,
            profile,
            security,
            radius,
            data,
        )

    # ==========================================================================
    # ZiGate+ (v2) Specific Methods
    # ==========================================================================

    def is_zigate_plus(self, version: tuple) -> bool:
        """
        Check if connected ZiGate is a ZiGate+ (v2).

        ZiGate+ uses version >= 5.0 (major version in high word).
        ZiGate v1 uses version 3.xx

        Args:
            version: Tuple from version() call (major, minor)

        Returns:
            True if ZiGate+ (v2), False if ZiGate v1
        """
        if version and len(version) >= 1:
            major = version[0]
            return major >= 5
        return False

    async def network_recovery_extract(self) -> bytes | None:
        """
        Extract network recovery data from ZiGate+ coordinator.

        Returns raw 72-byte network state for backup. This data includes:
        - Network identification (PAN ID, Extended PAN ID, channel)
        - Network security key
        - Frame counters
        - Trust center address

        Only supported on ZiGate+ (v2) with firmware >= 5.0

        Returns:
            72-byte recovery data, or None if failed
        """
        try:
            response = await self.command(
                CommandId.NETWORK_RECOVERY_EXTRACT,
                wait_response=ResponseId.NETWORK_RECOVERY_EXTRACT_RSP,
            )
            if response and len(response) > 0:
                data = response[0]
                if len(data) == NETWORK_RECOVERY_SIZE:
                    LOGGER.debug("Network recovery extract: %d bytes", len(data))
                    return data
                else:
                    LOGGER.warning(
                        "Unexpected recovery data size: %d (expected %d)",
                        len(data),
                        NETWORK_RECOVERY_SIZE,
                    )
            return None
        except Exception as e:
            LOGGER.error("Network recovery extract failed: %s", e)
            return None

    async def network_recovery_restore(self, recovery_data: bytes) -> bool:
        """
        Restore network state to ZiGate+ coordinator.

        Used for coordinator migration/backup restore. After restore,
        the coordinator will have the same network identity and security
        as the original, allowing devices to reconnect without re-pairing.

        Only supported on ZiGate+ (v2) with firmware >= 5.0

        Args:
            recovery_data: 72-byte network state from network_recovery_extract()

        Returns:
            True if restore was successful, False otherwise
        """
        if recovery_data is None:
            raise ValueError("Recovery data cannot be None")

        if len(recovery_data) != NETWORK_RECOVERY_SIZE:
            raise ValueError(
                f"Recovery data must be {NETWORK_RECOVERY_SIZE} bytes, "
                f"got {len(recovery_data)}"
            )

        try:
            response = await self.command(
                CommandId.NETWORK_RECOVERY_RESTORE,
                recovery_data,
                wait_response=ResponseId.NETWORK_RECOVERY_RESTORE_RSP,
            )
            if response and len(response) > 0:
                success = response[0] == 0
                if success:
                    LOGGER.info("Network recovery restore successful")
                else:
                    LOGGER.error("Network recovery restore returned error: %d", response[0])
                return success
            return False
        except Exception as e:
            LOGGER.error("Network recovery restore failed: %s", e)
            return False

    async def get_devices_list(self) -> list:
        """
        Get list of all devices in the network.

        Returns a list of DeviceEntry objects with:
        - id: Device ID
        - nwk: Network address (16-bit)
        - ieee: IEEE address (64-bit)
        - power_source: Power source type
        - link_quality: Link quality indicator

        Returns:
            List of DeviceEntry objects
        """
        try:
            response = await self.command(
                CommandId.GET_DEVICES_LIST,
                wait_response=ResponseId.GET_DEVICES_LIST,
            )
            if response and len(response) > 0:
                devices = response[0]
                LOGGER.debug("Got %d devices from coordinator", len(devices))
                return list(devices)
            return []
        except Exception as e:
            LOGGER.error("Failed to get devices list: %s", e)
            return []

    async def network_recovery_extract_ext(self) -> tuple[bytes, list] | None:
        """
        Extract extended network recovery data including device table.

        Returns raw network state AND device table for complete backup.
        This includes:
        - Network identification (PAN ID, Extended PAN ID, channel)
        - Network security key
        - Frame counters
        - Trust center address
        - Device table (IEEE to NWK address mappings)

        Structure layout (tsNwkRecoveryExt):
        - Offset 0-71: Base network recovery data (72 bytes)
        - Offset 72: u8DeviceCount (1 byte)
        - Offset 73-79: Reserved/padding (7 bytes for 8-byte alignment)
        - Offset 80+: Device entries (12 bytes each)

        Only supported on ZiGate+ (v2) with firmware >= 5.x

        Returns:
            Tuple of (raw_data bytes, list of device dicts) or None if failed
        """
        try:
            response = await self.command(
                CommandId.NETWORK_RECOVERY_EXTRACT_EXT,
                wait_response=ResponseId.NETWORK_RECOVERY_EXTRACT_EXT_RSP,
            )
            if response and len(response) > 0:
                data = response[0]
                if len(data) >= 80:  # 72 bytes network + 8 bytes header (aligned)
                    # Parse the extended structure
                    device_count = data[72]  # u8DeviceCount at offset 72
                    devices = []

                    # Devices start at offset 80 (8-byte aligned after 72 + 1 + 7 padding)
                    # Each device is 12 bytes: u64IeeeAddress (8) + u16NwkAddress (2) + padding (2)
                    offset = 80
                    for i in range(device_count):
                        if offset + 12 <= len(data):
                            # IEEE stored in little-endian
                            ieee_bytes = data[offset:offset+8]
                            ieee = int.from_bytes(ieee_bytes, "little")
                            nwk = int.from_bytes(data[offset+8:offset+10], "little")
                            devices.append({
                                "ieee": ieee,
                                "ieee_str": ieee_bytes[::-1].hex(),  # Display as big-endian
                                "nwk": nwk,
                            })
                            offset += 12

                    LOGGER.debug(
                        "Network recovery extract ext: %d bytes, %d devices",
                        len(data), len(devices)
                    )
                    return (data, devices)
                else:
                    LOGGER.warning("Unexpected recovery data size: %d (min 80)", len(data))
            return None
        except Exception as e:
            LOGGER.error("Network recovery extract ext failed: %s", e)
            return None

    async def network_recovery_restore_ext(
        self, recovery_data: bytes, devices: list = None
    ) -> bool:
        """
        Restore extended network state including device table.

        Used for complete coordinator migration/backup restore. After restore,
        the coordinator will have the same network identity, security, AND
        device table as the original.

        Structure layout (tsNwkRecoveryExt):
        - Offset 0-71: Base network recovery data (72 bytes)
        - Offset 72: u8DeviceCount (1 byte)
        - Offset 73-79: Reserved/padding (7 bytes for 8-byte alignment)
        - Offset 80+: Device entries (12 bytes each)

        Only supported on ZiGate+ (v2) with firmware >= 5.x

        Args:
            recovery_data: Raw data from network_recovery_extract_ext() (80+ bytes)
                          OR 72-byte network state with devices list provided separately
            devices: Optional list of device dicts with 'ieee' and 'nwk' keys
                    If None and recovery_data >= 80 bytes, uses embedded devices

        Returns:
            True if restore was successful, False otherwise
        """
        if recovery_data is None:
            raise ValueError("Recovery data cannot be None")

        if len(recovery_data) < NETWORK_RECOVERY_SIZE:
            raise ValueError(
                f"Recovery data must be at least {NETWORK_RECOVERY_SIZE} bytes, "
                f"got {len(recovery_data)}"
            )

        try:
            # If recovery_data already contains device table (from extract_ext),
            # we can send it directly
            if len(recovery_data) >= 80 and devices is None:
                ext_data = bytes(recovery_data)
                device_count = recovery_data[72]
            else:
                # Build extended structure from components
                # Base: 72 bytes network data
                ext_data = bytearray(recovery_data[:72])

                # Device count at offset 72
                if devices is None:
                    devices = []
                device_count = min(len(devices), 64)  # Max 64 devices

                # Offset 72: u8DeviceCount
                ext_data.append(device_count)
                # Offset 73-79: Reserved/padding (7 bytes for 8-byte alignment)
                ext_data.extend([0] * 7)

                # Device entries starting at offset 80 (12 bytes each)
                for device in devices[:device_count]:
                    ieee = device.get("ieee", 0)
                    nwk = device.get("nwk", 0xFFFF)

                    ext_data.extend(ieee.to_bytes(8, "little"))
                    ext_data.extend(nwk.to_bytes(2, "little"))
                    ext_data.extend([0, 0])  # 2 bytes padding for alignment

                ext_data = bytes(ext_data)

            LOGGER.debug(
                "Network recovery restore ext: %d bytes, %d devices",
                len(ext_data), device_count
            )

            response = await self.command(
                CommandId.NETWORK_RECOVERY_RESTORE_EXT,
                ext_data,
                wait_response=ResponseId.NETWORK_RECOVERY_RESTORE_EXT_RSP,
            )
            if response and len(response) > 0:
                success = response[0] == 0
                if success:
                    LOGGER.info(
                        "Network recovery restore ext successful: %d devices",
                        device_count
                    )
                else:
                    LOGGER.error("Network recovery restore ext error: %d", response[0])
                return success
            return False
        except Exception as e:
            LOGGER.error("Network recovery restore ext failed: %s", e)
            return False

    # ==========================================================================
    # OTA (Over-The-Air Update) Methods
    # ==========================================================================

    async def ota_load_image_header(
        self,
        addr_mode: int,
        address: int,
        file_identifier: int,
        header_version: int,
        header_length: int,
        header_control_field: int,
        manufacturer_code: int,
        image_type: int,
        file_version: int,
        stack_version: int,
        header_string: bytes,
        total_image_size: int,
        security_cred_version: int = 0,
        upgrade_file_dest: int = 0,
        min_hw_version: int = 0,
        max_hw_version: int = 0,
    ) -> bool:
        """
        Load OTA image header into the coordinator.

        This command prepares the coordinator to serve an OTA image.
        The actual image data is sent separately via ota_block_send().

        Args:
            addr_mode: Address mode (0x02=NWK, 0x04=broadcast)
            address: Target address for notification
            file_identifier: OTA file identifier (usually 0x0BEEF11E)
            header_version: Header version (usually 0x0100)
            header_length: Total header length
            header_control_field: Field control bits
            manufacturer_code: Image manufacturer code
            image_type: Image type identifier
            file_version: Firmware version number
            stack_version: Zigbee stack version
            header_string: 32-byte header string
            total_image_size: Total image size in bytes
            security_cred_version: Security credential version (optional)
            upgrade_file_dest: Target IEEE address (optional)
            min_hw_version: Minimum hardware version (optional)
            max_hw_version: Maximum hardware version (optional)

        Returns:
            True if header was loaded successfully
        """
        # Ensure header_string is exactly 32 bytes
        if isinstance(header_string, str):
            header_string = header_string.encode("utf-8")
        header_string = header_string[:32].ljust(32, b"\x00")

        try:
            await self.command(
                CommandId.OTA_LOAD_NEW_IMAGE,
                addr_mode,
                t.Address(t.AddressMode.NWK, address),
                file_identifier,
                header_version,
                header_length,
                header_control_field,
                manufacturer_code,
                image_type,
                file_version,
                stack_version,
                header_string,
                total_image_size,
                security_cred_version,
                upgrade_file_dest,
                min_hw_version,
                max_hw_version,
            )
            LOGGER.info(
                "OTA image header loaded: manufacturer=0x%04X, type=0x%04X, version=0x%08X, size=%d",
                manufacturer_code, image_type, file_version, total_image_size
            )
            return True
        except Exception as e:
            LOGGER.error("Failed to load OTA image header: %s", e)
            return False

    async def ota_image_notify(
        self,
        addr_mode: int = 0x04,  # Broadcast
        address: int = 0xFFFF,  # All devices
        src_endpoint: int = 1,
        dst_endpoint: int = 1,
        payload_type: int = 0,
        file_version: int = 0,
        image_type: int = 0xFFFF,
        manufacturer_code: int = 0xFFFF,
        query_jitter: int = 100,
    ) -> bool:
        """
        Notify devices that a new OTA image is available.

        This triggers devices to query for the image if they match the criteria.

        Args:
            addr_mode: Address mode (0x02=NWK unicast, 0x04=broadcast)
            address: Target address (NWK or broadcast 0xFFFF)
            src_endpoint: Source endpoint
            dst_endpoint: Destination endpoint
            payload_type: Notification payload type (0-3)
                0: Query jitter only
                1: + Manufacturer code
                2: + Image type
                3: + File version
            file_version: Image version to notify (if payload_type >= 3)
            image_type: Image type to notify (if payload_type >= 2)
            manufacturer_code: Manufacturer code (if payload_type >= 1)
            query_jitter: Random delay jitter (0-100)

        Returns:
            True if notification was sent successfully
        """
        try:
            await self.command(
                CommandId.OTA_IMAGE_NOTIFY,
                addr_mode,
                t.Address(t.AddressMode.NWK, address),
                src_endpoint,
                dst_endpoint,
                payload_type,
                file_version,
                image_type,
                manufacturer_code,
                query_jitter,
            )
            LOGGER.debug(
                "OTA image notify sent: addr=0x%04X, manufacturer=0x%04X, type=0x%04X",
                address, manufacturer_code, image_type
            )
            return True
        except Exception as e:
            LOGGER.error("Failed to send OTA image notify: %s", e)
            return False

    async def ota_block_send(
        self,
        src_endpoint: int,
        dst_endpoint: int,
        dst_address: int,
        addr_mode: int,
        sequence_no: int,
        status: int,
        file_offset: int,
        file_version: int,
        image_type: int,
        manufacturer_code: int,
        data: bytes,
    ) -> bool:
        """
        Send an OTA image block to a requesting device.

        This is called in response to an OTA_BLOCK_REQUEST from a device.

        Args:
            src_endpoint: Source endpoint
            dst_endpoint: Destination endpoint
            dst_address: Device NWK address
            addr_mode: Address mode (usually 0x02 for NWK)
            sequence_no: Sequence number from request
            status: Response status (0=success)
            file_offset: Offset of this block in the image
            file_version: Image version
            image_type: Image type
            manufacturer_code: Manufacturer code
            data: Block data (up to 64 bytes)

        Returns:
            True if block was sent successfully
        """
        # Limit block size to 64 bytes
        if len(data) > 64:
            data = data[:64]

        try:
            await self.command(
                CommandId.OTA_BLOCK_SEND,
                src_endpoint,
                dst_endpoint,
                dst_address,
                addr_mode,
                sequence_no,
                status,
                file_offset,
                file_version,
                image_type,
                manufacturer_code,
                data,
            )
            LOGGER.debug(
                "OTA block sent: addr=0x%04X, offset=%d, size=%d",
                dst_address, file_offset, len(data)
            )
            return True
        except Exception as e:
            LOGGER.error("Failed to send OTA block: %s", e)
            return False

    async def ota_upgrade_end_response(
        self,
        src_endpoint: int,
        dst_endpoint: int,
        dst_address: int,
        addr_mode: int,
        sequence_no: int,
        upgrade_time: int,
        current_time: int,
        file_version: int,
        image_type: int,
        manufacturer_code: int,
    ) -> bool:
        """
        Send upgrade end response to a device.

        This confirms the upgrade completion and tells the device when to apply it.

        Args:
            src_endpoint: Source endpoint
            dst_endpoint: Destination endpoint
            dst_address: Device NWK address
            addr_mode: Address mode (usually 0x02 for NWK)
            sequence_no: Sequence number
            upgrade_time: Time to apply upgrade (UTC seconds or 0xFFFFFFFF for immediate)
            current_time: Current time (UTC seconds)
            file_version: Image version
            image_type: Image type
            manufacturer_code: Manufacturer code

        Returns:
            True if response was sent successfully
        """
        try:
            await self.command(
                CommandId.OTA_UPGRADE_END_RESPONSE,
                src_endpoint,
                dst_endpoint,
                dst_address,
                addr_mode,
                sequence_no,
                upgrade_time,
                current_time,
                file_version,
                image_type,
                manufacturer_code,
            )
            LOGGER.info(
                "OTA upgrade end response sent: addr=0x%04X, version=0x%08X",
                dst_address, file_version
            )
            return True
        except Exception as e:
            LOGGER.error("Failed to send OTA upgrade end response: %s", e)
            return False

    async def ota_send_wait_for_data(
        self,
        src_endpoint: int,
        dst_endpoint: int,
        dst_address: int,
        addr_mode: int,
        current_time: int,
        request_time: int,
        block_request_delay_ms: int,
    ) -> bool:
        """
        Tell a device to wait before requesting the next block.

        Used for rate-limiting or pause/resume scenarios.

        Args:
            src_endpoint: Source endpoint
            dst_endpoint: Destination endpoint
            dst_address: Device NWK address
            addr_mode: Address mode
            current_time: Current time (UTC seconds)
            request_time: Time when device should request again
            block_request_delay_ms: Minimum delay between requests (ms)

        Returns:
            True if command was sent successfully
        """
        try:
            await self.command(
                CommandId.OTA_SEND_WAIT_FOR_DATA,
                src_endpoint,
                dst_endpoint,
                dst_address,
                addr_mode,
                current_time,
                request_time,
                block_request_delay_ms,
            )
            LOGGER.debug(
                "OTA wait for data sent: addr=0x%04X, delay=%dms",
                dst_address, block_request_delay_ms
            )
            return True
        except Exception as e:
            LOGGER.error("Failed to send OTA wait for data: %s", e)
            return False
