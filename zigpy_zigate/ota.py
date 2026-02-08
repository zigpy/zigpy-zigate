"""
ZiGate OTA (Over-The-Air Update) Module

This module provides OTA image serving capabilities for ZiGate coordinators.
It handles:
- Loading and parsing OTA image files
- Responding to device block requests
- Managing upgrade completion

Compatible with zigpy's OTA provider framework.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Callable, Any

from zigpy_zigate.types import (
    OTAImageHeader,
    OTABlockRequest,
    OTAUpgradeEndRequest,
    OTA_FILE_IDENTIFIER,
)

if TYPE_CHECKING:
    from zigpy_zigate.api import ZiGate

LOGGER = logging.getLogger(__name__)

# OTA constants
OTA_MAX_BLOCK_SIZE = 64
OTA_DEFAULT_QUERY_JITTER = 100


class OTAImage:
    """
    Represents a single OTA firmware image.

    Handles loading, parsing, and serving image data.
    """

    def __init__(self, path: Path | str = None):
        self.path: Optional[Path] = Path(path) if path else None
        self.header: Optional[OTAImageHeader] = None
        self._data: Optional[bytes] = None
        self._loaded = False

    @property
    def data(self) -> bytes:
        """Get image data, loading from file if needed"""
        if self._data is None and self.path:
            self.load()
        return self._data or b""

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def key(self) -> tuple:
        """Unique key for this image (manufacturer, image_type, version)"""
        if self.header:
            return self.header.image_key
        return (0, 0, 0)

    def load(self) -> bool:
        """Load image from file"""
        if not self.path or not self.path.exists():
            LOGGER.error("OTA image file not found: %s", self.path)
            return False

        try:
            with open(self.path, "rb") as f:
                self._data = f.read()

            if len(self._data) < 56:
                LOGGER.error("OTA image too small: %d bytes", len(self._data))
                return False

            # Parse header
            self.header = OTAImageHeader.from_bytes(self._data)

            # Verify file size matches header
            if len(self._data) != self.header.total_image_size:
                LOGGER.warning(
                    "OTA image size mismatch: file=%d, header=%d",
                    len(self._data),
                    self.header.total_image_size,
                )

            self._loaded = True
            LOGGER.info(
                "OTA image loaded: %s - %s",
                self.path.name,
                self.header,
            )
            return True

        except Exception as e:
            LOGGER.error("Failed to load OTA image %s: %s", self.path, e)
            return False

    def get_block(self, offset: int, size: int = OTA_MAX_BLOCK_SIZE) -> bytes:
        """Get a block of image data at the specified offset"""
        data = self.data
        if offset >= len(data):
            return b""
        return data[offset : offset + size]

    def matches(
        self,
        manufacturer_code: int,
        image_type: int,
        current_version: int = None,
    ) -> bool:
        """Check if this image matches the requested criteria"""
        if not self.header:
            return False

        if self.header.manufacturer_code != manufacturer_code:
            return False

        if self.header.image_type != image_type:
            return False

        # If current version provided, only match if this is newer
        if current_version is not None:
            if self.header.file_version <= current_version:
                return False

        return True

    def __repr__(self) -> str:
        if self.header:
            return f"OTAImage({self.path}, {self.header})"
        return f"OTAImage({self.path}, not loaded)"


class OTAImageProvider:
    """
    OTA Image Provider for ZiGate.

    Manages a collection of OTA images and provides them to requesting devices.
    Can be configured with a directory to scan for images.
    """

    def __init__(self, image_dir: Path | str = None):
        self._images: Dict[tuple, OTAImage] = {}  # key -> OTAImage
        self._image_dir: Optional[Path] = Path(image_dir) if image_dir else None
        self._auto_scan = True

    @property
    def images(self) -> list[OTAImage]:
        """List all loaded images"""
        return list(self._images.values())

    def add_image(self, image: OTAImage) -> bool:
        """Add an image to the provider"""
        if not image.loaded:
            if not image.load():
                return False

        self._images[image.key] = image
        LOGGER.info("OTA image added: %s", image.key)
        return True

    def add_image_from_file(self, path: Path | str) -> Optional[OTAImage]:
        """Load and add an image from a file"""
        image = OTAImage(path)
        if self.add_image(image):
            return image
        return None

    def remove_image(self, key: tuple) -> bool:
        """Remove an image by its key"""
        if key in self._images:
            del self._images[key]
            LOGGER.info("OTA image removed: %s", key)
            return True
        return False

    def get_image(
        self,
        manufacturer_code: int,
        image_type: int,
        current_version: int = None,
    ) -> Optional[OTAImage]:
        """
        Find a matching image for the given criteria.

        If current_version is provided, only returns images with newer versions.
        """
        for image in self._images.values():
            if image.matches(manufacturer_code, image_type, current_version):
                return image
        return None

    def scan_directory(self, directory: Path | str = None) -> int:
        """
        Scan a directory for OTA image files.

        Returns the number of images loaded.
        """
        scan_dir = Path(directory) if directory else self._image_dir
        if not scan_dir or not scan_dir.exists():
            LOGGER.warning("OTA image directory not found: %s", scan_dir)
            return 0

        count = 0
        for ext in ("*.ota", "*.zigbee", "*.bin"):
            for path in scan_dir.glob(ext):
                try:
                    image = OTAImage(path)
                    if image.load():
                        # Only add if valid OTA file
                        if image.header and image.header.file_identifier == OTA_FILE_IDENTIFIER:
                            self._images[image.key] = image
                            count += 1
                except Exception as e:
                    LOGGER.debug("Skipping %s: %s", path, e)

        LOGGER.info("Scanned %s: found %d OTA images", scan_dir, count)
        return count


class OTAManager:
    """
    OTA Manager for ZiGate.

    Handles the complete OTA update flow:
    1. Image registration and management
    2. Responding to device queries (via OTA cluster)
    3. Serving image blocks to devices
    4. Managing upgrade completion

    This class integrates with the ZiGate API to handle OTA-related
    callbacks and send responses.
    """

    def __init__(self, api: "ZiGate"):
        self._api = api
        self._provider = OTAImageProvider()
        self._active_transfers: Dict[int, dict] = {}  # nwk_addr -> transfer info
        self._callbacks: Dict[str, list[Callable]] = {
            "block_request": [],
            "upgrade_end": [],
            "transfer_complete": [],
            "transfer_failed": [],
        }
        self._sequence_no = 0

    @property
    def provider(self) -> OTAImageProvider:
        """Access the image provider"""
        return self._provider

    @property
    def active_transfers(self) -> Dict[int, dict]:
        """Get currently active transfers"""
        return self._active_transfers

    def set_image_directory(self, directory: Path | str) -> int:
        """Set the OTA image directory and scan for images"""
        self._provider._image_dir = Path(directory)
        return self._provider.scan_directory()

    def add_callback(self, event: str, callback: Callable) -> None:
        """Add a callback for OTA events"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def remove_callback(self, event: str, callback: Callable) -> None:
        """Remove a callback"""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)

    def _fire_callback(self, event: str, *args, **kwargs) -> None:
        """Fire callbacks for an event"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                LOGGER.error("OTA callback error (%s): %s", event, e)

    async def notify_image_available(
        self,
        manufacturer_code: int = 0xFFFF,
        image_type: int = 0xFFFF,
        file_version: int = 0,
        address: int = 0xFFFF,  # Broadcast
    ) -> bool:
        """
        Notify devices that a new OTA image is available.

        Args:
            manufacturer_code: Filter by manufacturer (0xFFFF = all)
            image_type: Filter by image type (0xFFFF = all)
            file_version: Specific version to notify (0 = any)
            address: Target address (0xFFFF = broadcast)

        Returns:
            True if notification was sent
        """
        # Determine payload type based on what's specified
        payload_type = 0
        if manufacturer_code != 0xFFFF:
            payload_type = 1
        if image_type != 0xFFFF:
            payload_type = 2
        if file_version != 0:
            payload_type = 3

        addr_mode = 0x04 if address == 0xFFFF else 0x02

        return await self._api.ota_image_notify(
            addr_mode=addr_mode,
            address=address,
            src_endpoint=1,
            dst_endpoint=1,
            payload_type=payload_type,
            file_version=file_version,
            image_type=image_type,
            manufacturer_code=manufacturer_code,
            query_jitter=OTA_DEFAULT_QUERY_JITTER,
        )

    async def handle_block_request(self, request: OTABlockRequest) -> bool:
        """
        Handle an OTA block request from a device.

        This is called when the ZiGate receives an OTA_BLOCK_REQUEST (0x8501).

        Args:
            request: The parsed block request

        Returns:
            True if block was sent successfully
        """
        nwk_addr = request.nwk_address
        manufacturer = request.manufacturer_code
        image_type = request.image_type
        offset = request.file_offset
        max_size = min(request.max_data_size, OTA_MAX_BLOCK_SIZE)

        LOGGER.debug(
            "OTA block request: addr=0x%04X, offset=%d, manufacturer=0x%04X, type=0x%04X",
            nwk_addr, offset, manufacturer, image_type
        )

        # Find matching image
        image = self._provider.get_image(manufacturer, image_type)
        if not image:
            LOGGER.warning(
                "No OTA image found for manufacturer=0x%04X, type=0x%04X",
                manufacturer, image_type
            )
            # Send error response
            return await self._api.ota_block_send(
                src_endpoint=1,
                dst_endpoint=request.src_endpoint,
                dst_address=nwk_addr,
                addr_mode=0x02,
                sequence_no=self._get_sequence(),
                status=0x95,  # ABORT
                file_offset=offset,
                file_version=request.file_version,
                image_type=image_type,
                manufacturer_code=manufacturer,
                data=b"",
            )

        # Get block data
        block_data = image.get_block(offset, max_size)

        # Track transfer
        if nwk_addr not in self._active_transfers:
            self._active_transfers[nwk_addr] = {
                "image": image,
                "start_time": time.time(),
                "bytes_sent": 0,
                "last_offset": 0,
            }

        transfer = self._active_transfers[nwk_addr]
        transfer["last_offset"] = offset
        transfer["bytes_sent"] += len(block_data)

        # Calculate progress
        total_size = image.header.total_image_size
        progress = (offset + len(block_data)) / total_size * 100

        if offset % 10000 < max_size:  # Log every ~10KB
            LOGGER.info(
                "OTA transfer 0x%04X: %.1f%% (%d/%d bytes)",
                nwk_addr, progress, offset + len(block_data), total_size
            )

        # Fire callback
        self._fire_callback("block_request", nwk_addr, offset, len(block_data), progress)

        # Send block
        return await self._api.ota_block_send(
            src_endpoint=1,
            dst_endpoint=request.src_endpoint,
            dst_address=nwk_addr,
            addr_mode=0x02,
            sequence_no=self._get_sequence(),
            status=0x00,  # SUCCESS
            file_offset=offset,
            file_version=image.header.file_version,
            image_type=image.header.image_type,
            manufacturer_code=image.header.manufacturer_code,
            data=block_data,
        )

    async def handle_upgrade_end_request(self, request: OTAUpgradeEndRequest) -> bool:
        """
        Handle an OTA upgrade end request from a device.

        This is called when the device has finished downloading and is ready
        to apply the upgrade.

        Args:
            request: The parsed upgrade end request

        Returns:
            True if response was sent successfully
        """
        nwk_addr = request.nwk_address
        status = request.status

        LOGGER.info(
            "OTA upgrade end request: addr=0x%04X, status=0x%02X, version=0x%08X",
            nwk_addr, status, request.file_version
        )

        # Get transfer info
        transfer = self._active_transfers.pop(nwk_addr, None)
        if transfer:
            elapsed = time.time() - transfer["start_time"]
            bytes_sent = transfer["bytes_sent"]
            speed = bytes_sent / elapsed if elapsed > 0 else 0
            LOGGER.info(
                "OTA transfer complete: 0x%04X, %d bytes in %.1fs (%.1f bytes/s)",
                nwk_addr, bytes_sent, elapsed, speed
            )

        # Fire callback
        self._fire_callback("upgrade_end", nwk_addr, status, request.file_version)

        if request.success:
            # Send upgrade response with immediate upgrade time
            result = await self._api.ota_upgrade_end_response(
                src_endpoint=1,
                dst_endpoint=request.src_endpoint,
                dst_address=nwk_addr,
                addr_mode=0x02,
                sequence_no=self._get_sequence(),
                upgrade_time=0xFFFFFFFF,  # Upgrade immediately
                current_time=int(time.time()),
                file_version=request.file_version,
                image_type=request.image_type,
                manufacturer_code=request.manufacturer_code,
            )

            if result:
                self._fire_callback("transfer_complete", nwk_addr, request.file_version)

            return result
        else:
            LOGGER.warning("OTA upgrade failed for 0x%04X: status=0x%02X", nwk_addr, status)
            self._fire_callback("transfer_failed", nwk_addr, status)
            return False

    def _get_sequence(self) -> int:
        """Get next sequence number"""
        self._sequence_no = (self._sequence_no + 1) & 0xFF
        return self._sequence_no

    def get_transfer_status(self, nwk_addr: int) -> Optional[dict]:
        """Get status of an active transfer"""
        if nwk_addr not in self._active_transfers:
            return None

        transfer = self._active_transfers[nwk_addr]
        image = transfer["image"]
        total_size = image.header.total_image_size
        bytes_sent = transfer["bytes_sent"]
        elapsed = time.time() - transfer["start_time"]

        return {
            "nwk_addr": nwk_addr,
            "image": image.key,
            "progress": bytes_sent / total_size * 100,
            "bytes_sent": bytes_sent,
            "total_size": total_size,
            "elapsed": elapsed,
            "speed": bytes_sent / elapsed if elapsed > 0 else 0,
        }


# =============================================================================
# Callback handler registration for ZiGate API
# =============================================================================

def register_ota_callbacks(api: "ZiGate", manager: OTAManager) -> None:
    """
    Register OTA callback handlers with the ZiGate API.

    This connects the OTA responses from ZiGate to the OTAManager.
    """
    from zigpy_zigate.api import ResponseId

    original_callback = api.handle_callback if hasattr(api, 'handle_callback') else None

    def ota_callback_handler(response_id, data):
        """Handle OTA-related callbacks"""
        if response_id == ResponseId.OTA_BLOCK_REQUEST:
            request = OTABlockRequest.from_response(data)
            asyncio.create_task(manager.handle_block_request(request))
        elif response_id == ResponseId.OTA_UPGRADE_END_REQUEST:
            request = OTAUpgradeEndRequest.from_response(data)
            asyncio.create_task(manager.handle_upgrade_end_request(request))
        elif original_callback:
            original_callback(response_id, data)

    api.handle_callback = ota_callback_handler
