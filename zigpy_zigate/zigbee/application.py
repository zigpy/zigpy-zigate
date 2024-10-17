from __future__ import annotations

import asyncio
import importlib.metadata
import logging
from typing import Any

import zigpy.application
import zigpy.config
import zigpy.device
import zigpy.exceptions
import zigpy.types
import zigpy.util
import zigpy.zdo

from zigpy_zigate import common as c, types as t
from zigpy_zigate.api import (
    PDM_EVENT,
    CommandNotSupportedError,
    NoResponseError,
    ResponseId,
    ZiGate,
)

LIB_VERSION = importlib.metadata.version("zigpy-zigate")
LOGGER = logging.getLogger(__name__)


class ControllerApplication(zigpy.application.ControllerApplication):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._api: ZiGate | None = None

        self._pending = {}
        self._pending_join = []

        self.version: str = ""

    async def _watchdog_feed(self):
        await self._api.set_time()

    async def connect(self):
        api = await ZiGate.new(self._config[zigpy.config.CONF_DEVICE], self)
        await api.set_raw_mode()
        await api.set_time()

        (_, version), lqi = await api.version()
        major, minor = version.to_bytes(2, "big")
        self.version = f"{major:x}.{minor:x}"

        self._api = api

        if self.version < "3.21":
            LOGGER.error(
                "Old ZiGate firmware detected, you should upgrade to 3.21 or newer"
            )

    async def disconnect(self):
        # TODO: how do you stop the network? Is it possible?
        if self._api is not None:
            try:
                await self._api.reset(wait=False)
            except Exception as e:
                LOGGER.warning("Failed to reset before disconnect: %s", e)
            finally:
                self._api.close()
                self._api = None

    async def start_network(self):
        # TODO: how do you start the network? Is it always automatically started?
        dev = self.add_device(
            ieee=self.state.node_info.ieee, nwk=self.state.node_info.nwk
        )
        await dev.schedule_initialize()

    async def load_network_info(self, *, load_devices: bool = False):
        network_state, lqi = await self._api.get_network_state()

        if not network_state or network_state[3] == 0 or network_state[0] == 0xFFFF:
            raise zigpy.exceptions.NetworkNotFormed()

        port = self._config[zigpy.config.CONF_DEVICE][zigpy.config.CONF_DEVICE_PATH]

        if c.is_zigate_wifi(port):
            model = "ZiGate WiFi"
        elif await c.async_is_pizigate(port):
            model = "PiZiGate"
        elif await c.async_is_zigate_din(port):
            model = "ZiGate USB-DIN"
        else:
            model = "ZiGate USB-TTL"

        self.state.node_info = zigpy.state.NodeInfo(
            nwk=zigpy.types.NWK(network_state[0]),
            ieee=zigpy.types.EUI64(network_state[1]),
            logical_type=zigpy.zdo.types.LogicalType.Coordinator,
            model=model,
            manufacturer="ZiGate",
            version=self.version,
        )

        epid, _ = zigpy.types.ExtendedPanId.deserialize(
            zigpy.types.uint64_t(network_state[3]).serialize()
        )

        try:
            network_key_data = await self._api.get_network_key()
            network_key = zigpy.state.Key(key=network_key_data)
        except CommandNotSupportedError:
            network_key = zigpy.state.Key()

        self.state.network_info = zigpy.state.NetworkInfo(
            source=f"zigpy-zigate@{LIB_VERSION}",
            extended_pan_id=epid,
            pan_id=zigpy.types.PanId(network_state[2]),
            nwk_update_id=0,
            nwk_manager_id=zigpy.types.NWK(0x0000),
            channel=network_state[4],
            channel_mask=zigpy.types.Channels.from_channel_list([network_state[4]]),
            security_level=5,
            network_key=network_key,
            # tc_link_key=zigpy.state.Key(),
            children=[],
            key_table=[],
            nwk_addresses={},
            stack_specific={},
            metadata={
                "zigate": {
                    "version": self.version,
                }
            },
        )

        self.state.network_info.tc_link_key.partner_ieee = self.state.node_info.ieee

        if not load_devices:
            return

        for device in await self._api.get_devices_list():
            if device.power_source != 0:  # only battery-powered devices
                continue

            ieee = zigpy.types.EUI64(device.ieee_addr)
            self.state.network_info.children.append(ieee)
            self.state.network_info.nwk_addresses[ieee] = zigpy.types.NWK(
                device.short_addr
            )

    async def reset_network_info(self):
        await self._api.erase_persistent_data()

    async def write_network_info(self, *, network_info, node_info):
        LOGGER.warning("Setting the pan_id is not supported by ZiGate")

        await self.reset_network_info()
        await self._api.set_channel(network_info.channel)

        epid, _ = zigpy.types.uint64_t.deserialize(
            network_info.extended_pan_id.serialize()
        )
        await self._api.set_extended_panid(epid)

        network_formed, lqi = await self._api.start_network()

        if network_formed[0] not in (
            t.Status.Success,
            t.Status.IncorrectParams,
            t.Status.Busy,
        ):
            raise zigpy.exceptions.FormationFailure(
                f"Unexpected error starting network: {network_formed!r}"
            )

        LOGGER.warning("Starting network got status %s, wait...", network_formed[0])
        for attempt in range(3):
            await asyncio.sleep(1)

            try:
                await self.load_network_info()
            except zigpy.exceptions.NetworkNotFormed as e:
                if attempt == 2:
                    raise zigpy.exceptions.FormationFailure() from e

    async def permit_with_link_key(self, node, link_key, time_s=60):
        LOGGER.warning("ZiGate does not support joins with link keys")

    async def _move_network_to_channel(
        self, new_channel: int, *, new_nwk_update_id: int
    ) -> None:
        """Moves the network to a new channel."""
        await self._api.set_channel(new_channel)

    async def energy_scan(
        self, channels: zigpy.types.Channels, duration_exp: int, count: int
    ) -> dict[int, float]:
        """Runs an energy detection scan and returns the per-channel scan results."""

        LOGGER.warning("Coordinator does not support energy scanning")
        return {c: 0 for c in channels}

    async def force_remove(self, dev):
        await self._api.remove_device(self.state.node_info.ieee, dev.ieee)

    async def add_endpoint(self, descriptor):
        # ZiGate does not support adding new endpoints
        pass

    def zigate_callback_handler(self, msg, response, lqi):
        LOGGER.debug("zigate_callback_handler %s %s", msg, response)

        if msg == ResponseId.LEAVE_INDICATION:
            nwk = 0
            ieee = zigpy.types.EUI64(response[0])
            self.handle_leave(nwk, ieee)
        elif msg == ResponseId.DEVICE_ANNOUNCE:
            nwk = response[0]
            ieee = zigpy.types.EUI64(response[1])
            parent_nwk = 0
            self.handle_join(nwk, ieee, parent_nwk)
            # Temporary disable two stages pairing due to firmware bug
            # rejoin = response[3]
            # if nwk in self._pending_join or rejoin:
            #     LOGGER.debug('Finish pairing {} (2nd device announce)'.format(nwk))
            #     if nwk in self._pending_join:
            #         self._pending_join.remove(nwk)
            #     self.handle_join(nwk, ieee, parent_nwk)
            # else:
            #     LOGGER.debug('Start pairing {} (1st device announce)'.format(nwk))
            #     self._pending_join.append(nwk)
        elif msg == ResponseId.DATA_INDICATION:
            (
                status,
                profile_id,
                cluster_id,
                src_ep,
                dst_ep,
                src,
                dst,
                payload,
            ) = response

            packet = zigpy.types.ZigbeePacket(
                src=src.to_zigpy_type()[0],
                src_ep=src_ep,
                dst=dst.to_zigpy_type()[0],
                dst_ep=dst_ep,
                profile_id=profile_id,
                cluster_id=cluster_id,
                data=zigpy.types.SerializableBytes(payload),
                lqi=lqi,
                rssi=None,
            )

            self.packet_received(packet)
        elif msg == ResponseId.ACK_DATA:
            LOGGER.debug("ACK Data received %s %s", response[4], response[0])
            # disabled because of https://github.com/fairecasoimeme/ZiGate/issues/324
            # self._handle_frame_failure(response[4], response[0])
        elif msg == ResponseId.APS_DATA_CONFIRM:
            LOGGER.debug(
                "ZPS Event APS data confirm, message routed to %s %s",
                response[3],
                response[0],
            )
        elif msg == ResponseId.PDM_EVENT:
            try:
                event = PDM_EVENT(response[0]).name
            except ValueError:
                event = "Unknown event"
            LOGGER.debug("PDM Event %s %s, record %s", response[0], event, response[1])
        elif msg == ResponseId.APS_DATA_CONFIRM_FAILED:
            LOGGER.debug("APS Data confirm Fail %s %s", response[4], response[0])
            self._handle_frame_failure(response[4], response[0])
        elif msg == ResponseId.EXTENDED_ERROR:
            LOGGER.warning("Extended error code %s", response[0])

    def _handle_frame_failure(self, message_tag, status):
        try:
            send_fut = self._pending.pop(message_tag)
            send_fut.set_result(status)
        except KeyError:
            LOGGER.warning("Unexpected message send failure")
        except asyncio.futures.InvalidStateError as exc:
            LOGGER.debug(
                "Invalid state on future - probably duplicate response: %s", exc
            )

    async def send_packet(self, packet):
        LOGGER.debug("Sending packet %r", packet)

        # Firmwares 3.1d and below allow a couple of _NO_ACK packets to send but all
        # subsequent ones will fail. ACKs must be enabled.
        ack = (
            zigpy.types.TransmitOptions.ACK in packet.tx_options
            or self.version <= "3.1d"
        )

        try:
            (status, tsn, packet_type, _), _ = await self._api.raw_aps_data_request(
                addr=packet.dst.address,
                src_ep=(
                    1 if packet.dst_ep is None or packet.dst_ep > 0 else 0
                ),  # ZiGate only support endpoint 1
                dst_ep=packet.dst_ep or 0,
                profile=packet.profile_id,
                cluster=packet.cluster_id,
                payload=packet.data.serialize(),
                addr_mode=t.ZIGPY_TO_ZIGATE_ADDR_MODE[packet.dst.addr_mode, ack],
                radius=packet.radius,
            )
        except NoResponseError:
            raise zigpy.exceptions.DeliveryError("ZiGate did not respond to command")

        self._pending[tsn] = asyncio.get_running_loop().create_future()

        if status != t.Status.Success:
            self._pending.pop(tsn)

            # Firmwares 3.1d and below fail to send packets on every request
            if status == t.Status.InvalidParameter and self.version <= "3.1d":
                pass
            else:
                raise zigpy.exceptions.DeliveryError(
                    f"Failed to send packet: {status!r}", status=status
                )

        # disabled because of https://github.com/fairecasoimeme/ZiGate/issues/324
        # try:
        #     v = await asyncio.wait_for(send_fut, 120)
        # except asyncio.TimeoutError:
        #     return 1, "timeout waiting for message %s send ACK" % (sequence, )
        # finally:
        #     self._pending.pop(tsn)
        # return v, "Message sent"

    async def permit_ncp(self, time_s=60):
        assert 0 <= time_s <= 254
        status, lqi = await self._api.permit_join(time_s)
        if status[0] != t.Status.Success:
            await self._api.reset()
