"""
zigpy-zigate - ZiGate radio library for zigpy

This library provides support for ZiGate Zigbee coordinators with zigpy.
Extended to support ZiGate+ (ZiGate v2, NXP JN5189) with Network Recovery.

Supported devices:
- ZiGate USB-TTL
- ZiGate USB-DIN
- ZiGate WiFi
- PiZiGate (Raspberry Pi HAT)
- ZiGate+ (v2) - JN5189 based, with Network Recovery support

ZiGate+ specific features:
- Network Recovery: backup/restore coordinator state (commands 0x0600/0x0601)
- Enhanced stability with NXP JN5189 chip
- Version >= 5.0

Basic usage:
    import zigpy_zigate

    # The ControllerApplication is used by ZHA
    from zigpy_zigate.zigbee.application import ControllerApplication

ZiGate+ backup/restore example:
    app = ControllerApplication(config)
    await app.connect()

    # Backup (ZiGate+ only)
    backup = await app.backup_network_info()
    if backup:
        with open("backup.bin", "wb") as f:
            f.write(backup)

    # Restore (ZiGate+ only)
    with open("backup.bin", "rb") as f:
        backup = f.read()
    await app.restore_network_info(backup)
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("zigpy-zigate")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

# Expose main classes
from zigpy_zigate.api import ZiGate, CommandId, ResponseId
from zigpy_zigate.zigbee.application import ControllerApplication

__all__ = [
    "ZiGate",
    "CommandId",
    "ResponseId",
    "ControllerApplication",
    "__version__",
]
