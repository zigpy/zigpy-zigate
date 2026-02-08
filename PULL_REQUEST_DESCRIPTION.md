# Pull Request: ZiGate+ Network Recovery and OTA Support

## Summary

This PR adds support for **ZiGate+ (v2)** advanced features:
- **Network Recovery**: Backup/restore coordinator state for seamless migration
- **OTA Updates**: Over-The-Air firmware updates for Zigbee devices

## Motivation

ZiGate+ (v2) with NXP JN5189 chip introduced powerful new capabilities that were not exposed in zigpy-zigate. This PR enables:

1. **Coordinator Migration**: Users can now backup their network state and restore it to a new ZiGate+, keeping all devices paired
2. **Firmware Updates**: OTA updates for Zigbee devices like ZLinky, without needing third-party tools

## Requirements

**IMPORTANT**: This PR requires ZiGate+ (v2) firmware version **5.324** or higher.

Get the latest firmware from: https://github.com/fairecasoimeme/ZiGatev2

The firmware update includes:
- Network Recovery commands (0x0600-0x0603)
- Extended device table backup
- Bug fixes for permit join and binding table

## Changes

### New CommandId entries
```python
# OTA commands
OTA_LOAD_NEW_IMAGE = 0x0500
OTA_BLOCK_SEND = 0x0502
OTA_UPGRADE_END_RESPONSE = 0x0504
OTA_IMAGE_NOTIFY = 0x0505

# Network Recovery commands
NETWORK_RECOVERY_EXTRACT = 0x0600
NETWORK_RECOVERY_RESTORE = 0x0601
NETWORK_RECOVERY_EXTRACT_EXT = 0x0602
NETWORK_RECOVERY_RESTORE_EXT = 0x0603
```

### New ResponseId entries
```python
# OTA responses
OTA_BLOCK_REQUEST = 0x8501
OTA_UPGRADE_END_REQUEST = 0x8503

# Network Recovery responses
NETWORK_RECOVERY_EXTRACT_RSP = 0x8600
NETWORK_RECOVERY_RESTORE_RSP = 0x8601
NETWORK_RECOVERY_EXTRACT_EXT_RSP = 0x8602
NETWORK_RECOVERY_RESTORE_EXT_RSP = 0x8603
```

### New ZiGate API methods

#### Network Recovery
- `is_zigate_plus(version)` - Detect ZiGate+ (v2) by firmware version
- `network_recovery_extract()` - Extract 72-byte network state
- `network_recovery_restore(data)` - Restore network from backup
- `network_recovery_extract_ext()` - Extract with device table (up to 64 devices)
- `network_recovery_restore_ext(data)` - Full restore including devices

#### OTA Updates
- `ota_load_image_header(...)` - Prepare coordinator for OTA serving
- `ota_image_notify(...)` - Notify devices of available firmware
- `ota_block_send(...)` - Send image blocks to requesting devices
- `ota_upgrade_end_response(...)` - Confirm upgrade completion

## Testing

Tested with:
- ZiGate+ (v2) hardware, firmware 5.324
- ZLinky router OTA update (248KB image, ~10 min transfer at 400 B/s)
- Home Assistant ZHA integration

### Test procedure for Network Recovery:
```python
# Extract backup
backup = await api.network_recovery_extract()

# Restore backup (after replacing hardware)
await api.network_recovery_restore(backup)

# Extended backup with devices
backup_ext, devices = await api.network_recovery_extract_ext()
```

### Test procedure for OTA:
```python
# Load OTA image header
await api.ota_load_image_header(
    file_identifier=0x0BEEF11E,
    manufacturer_code=0x1037,
    image_type=0x0001,
    file_version=0x00000012,
    total_size=248094,
    ...
)

# Notify devices
await api.ota_image_notify(manufacturer_code=0x1037, image_type=0x0001)

# Handle block requests in callback
# Send blocks with api.ota_block_send(...)
```

## Backward Compatibility

- All changes are additive
- Existing ZiGate v1 functionality is unchanged
- Network Recovery methods will raise `CommandNotSupportedError` on ZiGate v1
- OTA methods require appropriate firmware support

## Related

- ZiGatev2 firmware: https://github.com/fairecasoimeme/ZiGatev2
- Firmware changelog: See `CHANGELOG_v3.24.md` in ZiGatev2 repo
