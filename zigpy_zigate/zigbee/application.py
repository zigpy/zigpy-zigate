import asyncio
import logging
from typing import Any, Dict, Optional

import zigpy.application
import zigpy.config
import zigpy.device
import zigpy.types
import zigpy.util

from zigpy_zigate import types as t
from zigpy_zigate import common as c
from zigpy_zigate.api import NoResponseError, ZiGate, PDM_EVENT
from zigpy_zigate.config import CONF_DEVICE, CONF_DEVICE_PATH, CONFIG_SCHEMA, SCHEMA_DEVICE

LOGGER = logging.getLogger(__name__)


class ControllerApplication(zigpy.application.ControllerApplication):
    SCHEMA = CONFIG_SCHEMA
    SCHEMA_DEVICE = SCHEMA_DEVICE

    probe = ZiGate.probe

    def __init__(self, config: Dict[str, Any]):
        super().__init__(zigpy.config.ZIGPY_SCHEMA(config))
        self._api: Optional[ZiGate] = None

        self._pending = {}
        self._pending_join = []

        self._nwk = 0
        self._ieee = 0
        self.version = ''

    async def startup(self, auto_form=False):
        """Perform a complete application startup"""
        self._api = await ZiGate.new(self._config[CONF_DEVICE], self)
        await self._api.set_raw_mode()
        await self._api.set_time()
        version, lqi = await self._api.version()
        version = '{:x}'.format(version[1])
        version = '{}.{}'.format(version[0], version[1:])
        self.version = version
        if version < '3.1d':
            LOGGER.warning('Old ZiGate firmware detected, you should upgrade to 3.1d or newer')

        network_state, lqi = await self._api.get_network_state()
        should_form = not network_state or network_state[0] == 0xffff or network_state[3] == 0

        if auto_form and should_form:
            await self.form_network()
        if should_form:
            network_state, lqi = await self._api.get_network_state()
        self._nwk = network_state[0]
        self._ieee = zigpy.types.EUI64(network_state[1])

        dev = ZiGateDevice(self, self._ieee, self._nwk)
        self.devices[dev.ieee] = dev

    async def shutdown(self):
        """Shutdown application."""
        if self._api:
            self._api.close()

    async def form_network(self, channel=None, pan_id=None, extended_pan_id=None):
        await self._api.set_channel(channel)
        if pan_id:
            LOGGER.warning('Setting pan_id is not supported by ZiGate')
#             self._api.set_panid(pan_id)
        if extended_pan_id:
            await self._api.set_extended_panid(extended_pan_id)

        network_formed, lqi = await self._api.start_network()
        if network_formed[0] in (0, 1, 4):
            LOGGER.info('Network started %s %s',
                        network_formed[1],
                        network_formed[2])
            self._nwk = network_formed[1]
            self._ieee = network_formed[2]
        else:
            LOGGER.warning('Starting network got status %s, wait...', network_formed[0])
            tries = 3
            while tries > 0:
                await asyncio.sleep(1)
                tries -= 1
                network_state, lqi = await self._api.get_network_state()
                if network_state and network_state[3] != 0 and network_state[0] != 0xffff:
                    break
            if tries <= 0:
                LOGGER.error('Failed to start network error %s', network_formed[0])
                LOGGER.debug('Resetting ZiGate')
                await self._api.reset()

    async def force_remove(self, dev):
        await self._api.remove_device(self._ieee, dev.ieee)

    def zigate_callback_handler(self, msg, response, lqi):
        LOGGER.debug('zigate_callback_handler {}'.format(response))

        if msg == 0x8048:  # leave
            nwk = 0
            ieee = zigpy.types.EUI64(response[0])
            self.handle_leave(nwk, ieee)
        elif msg == 0x004D:  # join
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
        elif msg == 0x8002:
            if response[1] == 0x0 and response[2] == 0x13:
                nwk = response[5].address
                ieee = zigpy.types.EUI64(response[7][3:11])
                parent_nwk = 0
                self.handle_join(nwk, ieee, parent_nwk)
                return
            try:
                if response[5].address_mode == t.ADDRESS_MODE.NWK:
                    device = self.get_device(nwk=response[5].address)
                elif response[5].address_mode == t.ADDRESS_MODE.IEEE:
                    device = self.get_device(ieee=zigpy.types.EUI64(response[5].address))
                else:
                    LOGGER.error("No such device %s", response[5].address)
                    return
            except KeyError:
                LOGGER.debug("No such device %s", response[5].address)
                return
            rssi = 0
            device.radio_details(lqi, rssi)
            self.handle_message(device, response[1],
                                response[2],
                                response[3], response[4], response[-1])
        elif msg == 0x8011:  # ACK Data
            LOGGER.debug('ACK Data received %s %s', response[4], response[0])
            # disabled because of https://github.com/fairecasoimeme/ZiGate/issues/324
            # self._handle_frame_failure(response[4], response[0])
        elif msg == 0x8012:  # Push to next hope. APDU/NPDU freed
            LOGGER.debug('8012 Data received %s %s', response[4], response[0])
        elif msg == 0x8035:  # PDM Event
            try:
                event = PDM_EVENT(response[0]).name
            except ValueError:
                event = 'Unknown event'
            LOGGER.debug('PDM Event %s %s, record %s', response[0], event, response[1])
        elif msg == 0x8702:  # APS Data confirm Fail
            LOGGER.debug('APS Data confirm Fail %s %s', response[4], response[0])
            self._handle_frame_failure(response[4], response[0])

    def _handle_frame_failure(self, message_tag, status):
        try:
            send_fut = self._pending.pop(message_tag)
            send_fut.set_result(status)
        except KeyError:
            LOGGER.warning("Unexpected message send failure")
        except asyncio.futures.InvalidStateError as exc:
            LOGGER.debug("Invalid state on future - probably duplicate response: %s", exc)

    @zigpy.util.retryable_request
    async def request(self, device, profile, cluster, src_ep, dst_ep, sequence, data,
                      expect_reply=True, use_ieee=False):
        return await self._request(device.nwk, profile, cluster, src_ep, dst_ep, sequence, data,
        expect_reply, use_ieee)

    async def mrequest(self, group_id, profile, cluster, src_ep, sequence, data, *, hops=0, non_member_radius=3):
        src_ep = 1
        return await self._request(group_id, profile, cluster, src_ep, src_ep, sequence, data, addr_mode=1)
    
    async def _request(self, nwk, profile, cluster, src_ep, dst_ep, sequence, data,
                      expect_reply=True, use_ieee=False, addr_mode=2):
        src_ep = 1 if dst_ep else 0  # ZiGate only support endpoint 1
        LOGGER.debug('request %s',
                     (nwk, profile, cluster, src_ep, dst_ep, sequence, data, expect_reply, use_ieee))
        try:
            v, lqi = await self._api.raw_aps_data_request(nwk, src_ep, dst_ep, profile, cluster, data, addr_mode)
        except NoResponseError:
            return 1, "ZiGate doesn't answer to command"
        req_id = v[1]
        send_fut = asyncio.Future()
        self._pending[req_id] = send_fut

        if v[0] != 0:
            self._pending.pop(req_id)
            return v[0], "Message send failure {}".format(v[0])

        # disabled because of https://github.com/fairecasoimeme/ZiGate/issues/324
        # try:
        #     v = await asyncio.wait_for(send_fut, 120)
        # except asyncio.TimeoutError:
        #     return 1, "timeout waiting for message %s send ACK" % (sequence, )
        # finally:
        #     self._pending.pop(req_id)
        # return v, "Message sent"
        return 0, "Message sent"

    async def permit_ncp(self, time_s=60):
        assert 0 <= time_s <= 254
        status, lqi = await self._api.permit_join(time_s)
        if status[0] != 0:
            await self._api.reset()

    async def broadcast(self, profile, cluster, src_ep, dst_ep, grpid, radius,
                        sequence, data, broadcast_address):
        LOGGER.debug("Broadcast not implemented.")


class ZiGateDevice(zigpy.device.Device):
    def __init__(self, application, ieee, nwk):
        """Initialize instance."""

        super().__init__(application, ieee, nwk)
        port = application._config[CONF_DEVICE][CONF_DEVICE_PATH]
        model = 'ZiGate USB-TTL'
        if c.is_zigate_wifi(port):
            model = 'ZiGate WiFi'
        elif c.is_pizigate(port):
            model = 'PiZiGate'
        elif c.is_zigate_din(port):
            model = 'ZiGate USB-DIN'
        self._model = '{} {}'.format(model, application.version)

    @property
    def manufacturer(self):
        return "ZiGate"

    @property
    def model(self):
        return self._model
