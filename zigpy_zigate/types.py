"""
ZiGate data types for serialization/deserialization

Extended to support ZiGate+ (v2) structures.
"""

from __future__ import annotations

import enum
import struct
from typing import Tuple


class int_t(int):
    """Base integer type with serialization support"""

    _signed = True
    _size = 1
    _byteorder = "big"

    def serialize(self) -> bytes:
        return self.to_bytes(self._size, self._byteorder, signed=self._signed)

    @classmethod
    def deserialize(cls, data: bytes) -> Tuple["int_t", int]:
        value = int.from_bytes(data[: cls._size], cls._byteorder, signed=cls._signed)
        return cls(value), cls._size


class int8s(int_t):
    _signed = True
    _size = 1


class int16s(int_t):
    _signed = True
    _size = 2


class int32s(int_t):
    _signed = True
    _size = 4


class int64s(int_t):
    _signed = True
    _size = 8


class uint8_t(int_t):
    _signed = False
    _size = 1


class uint16_t(int_t):
    _signed = False
    _size = 2


class uint32_t(int_t):
    _signed = False
    _size = 4


class uint64_t(int_t):
    _signed = False
    _size = 8


class Bytes(bytes):
    """Raw bytes type - passes through without length prefix"""

    def serialize(self) -> bytes:
        return self

    @classmethod
    def deserialize(cls, data: bytes) -> Tuple["Bytes", int]:
        # Consume all remaining data
        return cls(data), len(data)


class LBytes(bytes):
    """Length-prefixed bytes (1-byte length header)"""

    def serialize(self) -> bytes:
        return bytes([len(self)]) + self

    @classmethod
    def deserialize(cls, data: bytes) -> Tuple["LBytes", int]:
        if len(data) < 1:
            return cls(b""), 0
        length = data[0]
        return cls(data[1 : 1 + length]), 1 + length


class EUI64(bytes):
    """64-bit IEEE address (reversed byte order for display)"""

    def __new__(cls, value=None):
        if value is None:
            value = b"\x00" * 8
        if isinstance(value, str):
            value = bytes.fromhex(value.replace(":", ""))
        if isinstance(value, int):
            value = value.to_bytes(8, "big")
        if len(value) != 8:
            raise ValueError(f"EUI64 must be 8 bytes, got {len(value)}")
        return super().__new__(cls, value)

    def serialize(self) -> bytes:
        return bytes(reversed(self))

    @classmethod
    def deserialize(cls, data: bytes) -> Tuple["EUI64", int]:
        return cls(bytes(reversed(data[:8]))), 8

    def __str__(self) -> str:
        return ":".join(f"{b:02x}" for b in self)

    def __repr__(self) -> str:
        return f"EUI64('{self}')"


class NWK(uint16_t):
    """16-bit network address"""

    def __str__(self) -> str:
        return f"0x{self:04x}"

    def __repr__(self) -> str:
        return f"NWK({self})"


class AddressMode(enum.IntEnum):
    """Zigbee address modes"""

    BOUND = 0x00
    GROUP = 0x01
    NWK = 0x02
    IEEE = 0x03
    BROADCAST = 0x04
    NO_TRANSMIT = 0x05
    BOUND_NO_ACK = 0x06
    NWK_ACK = 0x07


class Status(enum.IntEnum):
    """ZiGate status codes"""

    SUCCESS = 0x00
    INCORRECT_PARAMETERS = 0x01
    UNHANDLED_COMMAND = 0x02
    COMMAND_FAILED = 0x03
    BUSY = 0x04
    STACK_ALREADY_STARTED = 0x05
    # ... additional status codes

    @classmethod
    def _missing_(cls, value):
        # Return a generic status for unknown values
        obj = int.__new__(cls, value)
        obj._name_ = f"UNKNOWN_{value:02X}"
        obj._value_ = value
        return obj


class LogLevel(enum.IntEnum):
    """Log levels"""

    EMERGENCY = 0
    ALERT = 1
    CRITICAL = 2
    ERROR = 3
    WARNING = 4
    NOTICE = 5
    INFO = 6
    DEBUG = 7


class Struct:
    """Base class for structured data"""

    _fields: list[tuple[str, type]] = []

    def __init__(self, **kwargs):
        for name, _ in self._fields:
            setattr(self, name, kwargs.get(name, None))

    def serialize(self) -> bytes:
        result = b""
        for name, dtype in self._fields:
            value = getattr(self, name)
            if hasattr(value, "serialize"):
                result += value.serialize()
            elif isinstance(value, bytes):
                result += value
            elif isinstance(value, int):
                result += dtype(value).serialize()
        return result

    @classmethod
    def deserialize(cls, data: bytes) -> Tuple["Struct", int]:
        instance = cls()
        offset = 0
        for name, dtype in cls._fields:
            if offset >= len(data):
                break
            value, consumed = dtype.deserialize(data[offset:])
            setattr(instance, name, value)
            offset += consumed
        return instance, offset


class Address:
    """Variable-length address based on mode"""

    def __init__(self, mode: AddressMode = AddressMode.NWK, address=None):
        self.mode = mode
        self.address = address

    def serialize(self) -> bytes:
        if self.mode == AddressMode.IEEE:
            if isinstance(self.address, EUI64):
                return self.address.serialize()
            return EUI64(self.address).serialize()
        elif self.mode in (AddressMode.NWK, AddressMode.GROUP):
            if isinstance(self.address, NWK):
                return self.address.serialize()
            return NWK(self.address).serialize()
        return b""

    @classmethod
    def deserialize(cls, data: bytes, mode: AddressMode = None) -> Tuple["Address", int]:
        if mode == AddressMode.IEEE:
            addr, consumed = EUI64.deserialize(data)
            return cls(mode, addr), consumed
        else:
            addr, consumed = NWK.deserialize(data)
            return cls(AddressMode.NWK, addr), consumed


class DeviceEntry:
    """Device entry from device list"""

    def __init__(self):
        self.id = 0
        self.nwk = NWK(0)
        self.ieee = EUI64()
        self.power_source = 0
        self.link_quality = 0

    @classmethod
    def deserialize(cls, data: bytes) -> Tuple["DeviceEntry", int]:
        if len(data) < 13:
            raise ValueError("DeviceEntry requires 13 bytes")

        entry = cls()
        entry.id = data[0]
        entry.nwk = NWK(int.from_bytes(data[1:3], "big"))
        entry.ieee = EUI64(bytes(reversed(data[3:11])))
        entry.power_source = data[11]
        entry.link_quality = data[12]
        return entry, 13


class DeviceEntryArray(list):
    """Array of device entries"""

    @classmethod
    def deserialize(cls, data: bytes) -> Tuple["DeviceEntryArray", int]:
        entries = cls()
        offset = 0
        while offset + 13 <= len(data):
            entry, consumed = DeviceEntry.deserialize(data[offset:])
            entries.append(entry)
            offset += consumed
        return entries, offset


# =============================================================================
# ZiGate+ (v2) Network Recovery Structure
# =============================================================================

class NetworkRecoveryData(Struct):
    """
    Network Recovery Data Structure for ZiGate+ (v2).

    This structure contains all essential network information needed for
    backup and restore of the coordinator state. Total size: 72 bytes.

    Matches tsNwkRecovery in firmware app_network_recovery.h
    """

    _fields = [
        # Header (4 bytes)
        ("version", uint8_t),
        ("reserved1", uint8_t),
        ("reserved2", uint8_t),
        ("reserved3", uint8_t),
        # Network Identification (20 bytes)
        ("ext_pan_id", uint64_t),
        ("ieee_address", uint64_t),
        ("pan_id", uint16_t),
        ("nwk_address", uint16_t),
        # Network Parameters (4 bytes)
        ("channel", uint8_t),
        ("nwk_update_id", uint8_t),
        ("depth", uint8_t),
        ("capability_info", uint8_t),
        # Security (20 bytes)
        # Note: nwk_key is 16 bytes, handled specially
        ("active_key_seq_num", uint8_t),
        ("security_level", uint8_t),
        ("reserved4", uint8_t),
        ("reserved5", uint8_t),
        # Frame Counters (8 bytes)
        ("outgoing_frame_counter", uint32_t),
        ("aps_frame_counter", uint32_t),
        # Trust Center (8 bytes)
        ("trust_center_address", uint64_t),
    ]

    NWK_KEY_OFFSET = 28  # Offset of network key in structure
    NWK_KEY_LENGTH = 16  # Length of network key

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.nwk_key = kwargs.get("nwk_key", b"\x00" * self.NWK_KEY_LENGTH)

    @classmethod
    def from_bytes(cls, data: bytes) -> "NetworkRecoveryData":
        """Parse network recovery data from raw bytes"""
        if len(data) != 72:
            raise ValueError(f"Expected 72 bytes, got {len(data)}")

        instance = cls()

        # Parse header
        instance.version = data[0]
        instance.reserved1 = data[1]
        instance.reserved2 = data[2]
        instance.reserved3 = data[3]

        # Parse network identification
        instance.ext_pan_id = int.from_bytes(data[4:12], "big")
        instance.ieee_address = int.from_bytes(data[12:20], "big")
        instance.pan_id = int.from_bytes(data[20:22], "big")
        instance.nwk_address = int.from_bytes(data[22:24], "big")

        # Parse network parameters
        instance.channel = data[24]
        instance.nwk_update_id = data[25]
        instance.depth = data[26]
        instance.capability_info = data[27]

        # Parse security
        instance.nwk_key = data[28:44]
        instance.active_key_seq_num = data[44]
        instance.security_level = data[45]
        instance.reserved4 = data[46]
        instance.reserved5 = data[47]

        # Parse frame counters
        instance.outgoing_frame_counter = int.from_bytes(data[48:52], "big")
        instance.aps_frame_counter = int.from_bytes(data[52:56], "big")

        # Parse trust center
        instance.trust_center_address = int.from_bytes(data[56:64], "big")

        return instance

    def to_bytes(self) -> bytes:
        """Serialize network recovery data to raw bytes"""
        data = bytearray(72)

        # Header
        data[0] = self.version or 1
        data[1] = self.reserved1 or 0
        data[2] = self.reserved2 or 0
        data[3] = self.reserved3 or 0

        # Network identification
        data[4:12] = (self.ext_pan_id or 0).to_bytes(8, "big")
        data[12:20] = (self.ieee_address or 0).to_bytes(8, "big")
        data[20:22] = (self.pan_id or 0).to_bytes(2, "big")
        data[22:24] = (self.nwk_address or 0).to_bytes(2, "big")

        # Network parameters
        data[24] = self.channel or 0
        data[25] = self.nwk_update_id or 0
        data[26] = self.depth or 0
        data[27] = self.capability_info or 0

        # Security
        if self.nwk_key:
            data[28:44] = self.nwk_key[:16].ljust(16, b"\x00")
        data[44] = self.active_key_seq_num or 0
        data[45] = self.security_level or 0
        data[46] = self.reserved4 or 0
        data[47] = self.reserved5 or 0

        # Frame counters
        data[48:52] = (self.outgoing_frame_counter or 0).to_bytes(4, "big")
        data[52:56] = (self.aps_frame_counter or 0).to_bytes(4, "big")

        # Trust center
        data[56:64] = (self.trust_center_address or 0).to_bytes(8, "big")

        # Padding
        data[64:72] = b"\x00" * 8

        return bytes(data)

    def __repr__(self) -> str:
        return (
            f"NetworkRecoveryData("
            f"version={self.version}, "
            f"pan_id=0x{self.pan_id or 0:04x}, "
            f"ext_pan_id=0x{self.ext_pan_id or 0:016x}, "
            f"channel={self.channel}, "
            f"nwk_address=0x{self.nwk_address or 0:04x})"
        )


# =============================================================================
# OTA (Over-The-Air Update) Structures
# =============================================================================

# OTA file identifier (magic number)
OTA_FILE_IDENTIFIER = 0x0BEEF11E

# OTA header versions
OTA_HEADER_VERSION_ZIGBEE = 0x0100


class OTAImageHeader:
    """
    OTA Image Header Structure.

    This structure contains the OTA upgrade image header as defined by the
    Zigbee OTA cluster specification (ZCL 6.0, Clause 11).

    Standard header size: 56 bytes (without optional fields)
    """

    # Header field control bits
    FIELD_CTRL_SECURITY_CREDENTIAL = 0x01
    FIELD_CTRL_DEVICE_SPECIFIC = 0x02
    FIELD_CTRL_HARDWARE_VERSION = 0x04

    def __init__(self):
        # Mandatory fields (always present)
        self.file_identifier = OTA_FILE_IDENTIFIER
        self.header_version = OTA_HEADER_VERSION_ZIGBEE
        self.header_length = 56  # Minimum header length
        self.header_control_field = 0
        self.manufacturer_code = 0
        self.image_type = 0
        self.file_version = 0
        self.stack_version = 0
        self.header_string = b"\x00" * 32
        self.total_image_size = 0

        # Optional fields (presence indicated by header_control_field)
        self.security_credential_version = 0
        self.upgrade_file_destination = 0
        self.min_hardware_version = 0
        self.max_hardware_version = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> "OTAImageHeader":
        """Parse OTA image header from raw bytes"""
        if len(data) < 56:
            raise ValueError(f"OTA header requires at least 56 bytes, got {len(data)}")

        instance = cls()

        # Parse mandatory fields
        instance.file_identifier = int.from_bytes(data[0:4], "little")
        if instance.file_identifier != OTA_FILE_IDENTIFIER:
            raise ValueError(
                f"Invalid OTA file identifier: 0x{instance.file_identifier:08X}"
            )

        instance.header_version = int.from_bytes(data[4:6], "little")
        instance.header_length = int.from_bytes(data[6:8], "little")
        instance.header_control_field = int.from_bytes(data[8:10], "little")
        instance.manufacturer_code = int.from_bytes(data[10:12], "little")
        instance.image_type = int.from_bytes(data[12:14], "little")
        instance.file_version = int.from_bytes(data[14:18], "little")
        instance.stack_version = int.from_bytes(data[18:20], "little")
        instance.header_string = data[20:52].rstrip(b"\x00")
        instance.total_image_size = int.from_bytes(data[52:56], "little")

        # Parse optional fields based on header_control_field
        offset = 56

        if instance.header_control_field & cls.FIELD_CTRL_SECURITY_CREDENTIAL:
            if offset < len(data):
                instance.security_credential_version = data[offset]
                offset += 1

        if instance.header_control_field & cls.FIELD_CTRL_DEVICE_SPECIFIC:
            if offset + 8 <= len(data):
                instance.upgrade_file_destination = int.from_bytes(
                    data[offset : offset + 8], "little"
                )
                offset += 8

        if instance.header_control_field & cls.FIELD_CTRL_HARDWARE_VERSION:
            if offset + 4 <= len(data):
                instance.min_hardware_version = int.from_bytes(
                    data[offset : offset + 2], "little"
                )
                instance.max_hardware_version = int.from_bytes(
                    data[offset + 2 : offset + 4], "little"
                )
                offset += 4

        return instance

    def to_bytes(self) -> bytes:
        """Serialize OTA image header to raw bytes"""
        data = bytearray()

        # Mandatory fields
        data.extend(self.file_identifier.to_bytes(4, "little"))
        data.extend(self.header_version.to_bytes(2, "little"))
        data.extend(self.header_length.to_bytes(2, "little"))
        data.extend(self.header_control_field.to_bytes(2, "little"))
        data.extend(self.manufacturer_code.to_bytes(2, "little"))
        data.extend(self.image_type.to_bytes(2, "little"))
        data.extend(self.file_version.to_bytes(4, "little"))
        data.extend(self.stack_version.to_bytes(2, "little"))

        # Header string (32 bytes, padded with zeros)
        header_str = self.header_string[:32].ljust(32, b"\x00")
        data.extend(header_str)

        data.extend(self.total_image_size.to_bytes(4, "little"))

        # Optional fields
        if self.header_control_field & self.FIELD_CTRL_SECURITY_CREDENTIAL:
            data.append(self.security_credential_version)

        if self.header_control_field & self.FIELD_CTRL_DEVICE_SPECIFIC:
            data.extend(self.upgrade_file_destination.to_bytes(8, "little"))

        if self.header_control_field & self.FIELD_CTRL_HARDWARE_VERSION:
            data.extend(self.min_hardware_version.to_bytes(2, "little"))
            data.extend(self.max_hardware_version.to_bytes(2, "little"))

        return bytes(data)

    @property
    def image_key(self) -> tuple:
        """Return unique key for this image (manufacturer, image_type, version)"""
        return (self.manufacturer_code, self.image_type, self.file_version)

    def __repr__(self) -> str:
        return (
            f"OTAImageHeader("
            f"manufacturer=0x{self.manufacturer_code:04X}, "
            f"image_type=0x{self.image_type:04X}, "
            f"version=0x{self.file_version:08X}, "
            f"size={self.total_image_size})"
        )


class OTABlockRequest:
    """
    OTA Block Request from a device.

    Received when a device requests an image block during OTA upgrade.

    ZiGate firmware format for 0x8501 response (from app_zcl_event_handler.c):

    CLUSTER_CUSTOM prefix (4 bytes):
    - Byte 0:      u8TransactionSequenceNumber
    - Byte 1:      u8SrcEndpoint
    - Bytes 2-3:   u16ClusterEnum (big-endian, 0x0019 for OTA)

    OTA Block Request data:
    - Byte 4:      u8SrcAddrMode
    - Bytes 5-6:   u16NwkAddr (big-endian)
    - Bytes 7-14:  u64RequestNodeAddress (IEEE, big-endian)
    - Bytes 15-18: u32FileOffset (big-endian)
    - Bytes 19-22: u32FileVersion (big-endian)
    - Bytes 23-24: u16ImageType (big-endian)
    - Bytes 25-26: u16ManufacturerCode (big-endian)
    - Bytes 27-28: u16BlockRequestDelay (big-endian)
    - Byte 29:     u8MaxDataSize
    - Byte 30:     u8FieldControl
    - Byte 31:     u8LinkQuality (added by SerialLink)
    """

    def __init__(self):
        self.seq_no = 0
        self.src_endpoint = 0
        self.cluster_id = 0x0019  # OTA cluster
        self.addr_mode = 0
        self.address = 0
        self.ieee_address = 0
        self.file_offset = 0
        self.file_version = 0
        self.image_type = 0
        self.manufacturer_code = 0
        self.block_request_delay = 0
        self.max_data_size = 64
        self.field_control = 0
        self.lqi = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> "OTABlockRequest":
        """Create from raw bytes received from ZiGate firmware"""
        instance = cls()
        if len(data) < 31:
            return instance

        # Parse prefix
        instance.seq_no = data[0]
        instance.src_endpoint = data[1]
        instance.cluster_id = int.from_bytes(data[2:4], "big")

        # Parse OTA data (starting at offset 4)
        instance.addr_mode = data[4]
        instance.address = int.from_bytes(data[5:7], "big")
        instance.ieee_address = int.from_bytes(data[7:15], "big")
        instance.file_offset = int.from_bytes(data[15:19], "big")
        instance.file_version = int.from_bytes(data[19:23], "big")
        instance.image_type = int.from_bytes(data[23:25], "big")
        instance.manufacturer_code = int.from_bytes(data[25:27], "big")
        instance.block_request_delay = int.from_bytes(data[27:29], "big")
        instance.max_data_size = data[29]
        instance.field_control = data[30] if len(data) > 30 else 0
        instance.lqi = data[31] if len(data) > 31 else 0

        return instance

    @classmethod
    def from_response(cls, response: tuple) -> "OTABlockRequest":
        """Create from parsed response tuple (legacy method)"""
        instance = cls()
        if len(response) >= 11:
            instance.src_endpoint = response[0]
            instance.cluster_id = response[1]
            instance.addr_mode = response[2]
            instance.address = response[3]
            instance.file_offset = response[4]
            instance.file_version = response[5]
            instance.image_type = response[6]
            instance.manufacturer_code = response[7]
            instance.block_request_delay = response[8]
            instance.max_data_size = response[9]
            instance.field_control = response[10]
        return instance

    @property
    def nwk_address(self) -> int:
        """Get network address from response"""
        if hasattr(self.address, "address"):
            return self.address.address
        return self.address

    def __repr__(self) -> str:
        return (
            f"OTABlockRequest("
            f"addr=0x{self.nwk_address:04X}, "
            f"offset={self.file_offset}, "
            f"manufacturer=0x{self.manufacturer_code:04X}, "
            f"image_type=0x{self.image_type:04X})"
        )


class OTAUpgradeEndRequest:
    """
    OTA Upgrade End Request from a device.

    Received when a device has finished downloading the image and is
    ready to apply the upgrade.

    ZiGate firmware format for 0x8503 response (from app_zcl_event_handler.c):

    CLUSTER_CUSTOM prefix (4 bytes):
    - Byte 0:      u8TransactionSequenceNumber
    - Byte 1:      u8SrcEndpoint
    - Bytes 2-3:   u16ClusterEnum (big-endian, 0x0019 for OTA)

    OTA Upgrade End Request data:
    - Byte 4:      u8SrcAddrMode
    - Bytes 5-6:   u16NwkAddr (big-endian)
    - Bytes 7-10:  u32FileVersion (big-endian)
    - Bytes 11-12: u16ImageType (big-endian)
    - Bytes 13-14: u16ManufacturerCode (big-endian)
    - Byte 15:     u8Status
    - Byte 16:     u8LinkQuality (added by SerialLink)
    """

    # Status codes
    STATUS_SUCCESS = 0x00
    STATUS_ABORT = 0x95
    STATUS_REQUIRE_MORE_IMAGE = 0x99

    def __init__(self):
        self.seq_no = 0
        self.src_endpoint = 0
        self.cluster_id = 0x0019
        self.addr_mode = 0
        self.address = 0
        self.file_version = 0
        self.image_type = 0
        self.manufacturer_code = 0
        self.status = 0
        self.lqi = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> "OTAUpgradeEndRequest":
        """Create from raw bytes received from ZiGate firmware"""
        instance = cls()
        if len(data) < 16:
            return instance

        # Parse prefix
        instance.seq_no = data[0]
        instance.src_endpoint = data[1]
        instance.cluster_id = int.from_bytes(data[2:4], "big")

        # Parse OTA data (starting at offset 4)
        instance.addr_mode = data[4]
        instance.address = int.from_bytes(data[5:7], "big")
        instance.file_version = int.from_bytes(data[7:11], "big")
        instance.image_type = int.from_bytes(data[11:13], "big")
        instance.manufacturer_code = int.from_bytes(data[13:15], "big")
        instance.status = data[15]
        instance.lqi = data[16] if len(data) > 16 else 0

        return instance

    @classmethod
    def from_response(cls, response: tuple) -> "OTAUpgradeEndRequest":
        """Create from parsed response tuple (legacy method)"""
        instance = cls()
        if len(response) >= 8:
            instance.src_endpoint = response[0]
            instance.cluster_id = response[1]
            instance.addr_mode = response[2]
            instance.address = response[3]
            instance.file_version = response[4]
            instance.image_type = response[5]
            instance.manufacturer_code = response[6]
            instance.status = response[7]
        return instance

    @property
    def nwk_address(self) -> int:
        """Get network address from response"""
        if hasattr(self.address, "address"):
            return self.address.address
        return self.address

    @property
    def success(self) -> bool:
        """Check if upgrade was successful"""
        return self.status == self.STATUS_SUCCESS

    def __repr__(self) -> str:
        return (
            f"OTAUpgradeEndRequest("
            f"addr=0x{self.nwk_address:04X}, "
            f"status=0x{self.status:02X}, "
            f"manufacturer=0x{self.manufacturer_code:04X}, "
            f"image_type=0x{self.image_type:04X})"
        )
