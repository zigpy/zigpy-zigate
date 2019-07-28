import asyncio
import logging

from zigpy.exceptions import DeliveryError
import zigpy.application
import zigpy.util
from zigpy_zigate import types as t

LOGGER = logging.getLogger(__name__)


class ControllerApplication(zigpy.application.ControllerApplication):
    def __init__(self, api, database_file=None):
        super().__init__(database_file=database_file)
        self._api = api
        self._api.add_callback(self.zigate_callback_handler)
        api.set_application(self)

        self._pending = {}
        self._zigate_seq = {}

        self._nwk = 0
        self._ieee = 0
        self.version = ''

    async def startup(self, auto_form=False):
        """Perform a complete application startup"""
        await self._api.set_raw_mode()
        version, lqi = await self._api.version()
        version = '{:x}'.format(version[1])
        version = '{}.{}'.format(version[0], version[1:])
        self.version = version

        network_state, lqi = await self._api.get_network_state()
        self._nwk = network_state[0]
        self._ieee = network_state[1]

        if auto_form:
            await self.form_network()

    async def shutdown(self):
        """Shutdown application."""
        self._api.close()

    async def form_network(self, channel=15, pan_id=None, extended_pan_id=None):
        await self._api.set_channel(channel)
        if pan_id:
            LOGGER.warning('Setting pan_id is not supported by ZiGate')
#             self._api.set_panid(pan_id)
        if extended_pan_id:
            await self._api.set_extended_panid(extended_pan_id)

    async def force_remove(self, dev):
        self._api.remove_device(self._ieee, dev.ieee)

    def zigate_callback_handler(self, msg, response, lqi):
        LOGGER.debug('zigate_callback_handler {}'.format(response))

        if msg == 0x8048:  # leave
            nwk = 0
            ieee = response[0]
            self.handle_leave(nwk, ieee)
        elif msg == 0x004D:  # join
            nwk = response[0]
            ieee = response[1]
            parent_nwk = 0
            self.handle_join(nwk, ieee, parent_nwk)
        elif msg == 0x8002:
            try:
                if response[5].address_mode == t.ADDRESS_MODE.NWK:
                    device = self.get_device(nwk=response[5].address)
                elif response[5].address_mode == t.ADDRESS_MODE.IEEE:
                    device = self.get_device(ieee=response[5].address)
                else:
                    LOGGER.error("No such device %s", response[5].address)
                    return
            except KeyError:
                LOGGER.debug("No such device %s", response[5].address)
                return
            rssi = 0
            device.radio_details(lqi, rssi)
            tsn, command_id, is_reply, args = self.deserialize(device, response[3],
                                                               response[2], response[-1])
            if is_reply:
                self._handle_reply(device, response, tsn, command_id, args)
            else:
                self.handle_message(device, False, response[1],
                                    response[2],
                                    response[3], response[4],
                                    tsn, command_id, args)
        elif msg == 0x8702:  # APS Data confirm Fail
            self._handle_frame_failure(response[4], response[0])

    def _handle_reply(self, sender, response, tsn, command_id, args):
        try:
            send_fut, reply_fut = self._pending[tsn]
            if send_fut.done():
                self._pending.pop(tsn)
            if reply_fut:
                reply_fut.set_result(args)
            return
        except KeyError:
            LOGGER.warning("Unexpected response TSN=%s command=%s args=%s", tsn, command_id, args)
        except asyncio.futures.InvalidStateError as exc:
            LOGGER.debug("Invalid state on future - probably duplicate response: %s", exc)
            # We've already handled, don't drop through to device handler
            return

        self.handle_message(sender, True, response['profile_id'],
                            response['cluster_id'], response['source_endpoint'], response['destination_endpoint'],
                            tsn, command_id, args)

    def _handle_frame_failure(self, message_tag, status):
        try:
            send_fut, reply_fut = self._pending.pop(message_tag)
            send_fut.set_exception(DeliveryError("Message send failure: %s" % (status, )))
            if reply_fut:
                reply_fut.cancel()
        except KeyError:
            LOGGER.warning("Unexpected message send failure")
        except asyncio.futures.InvalidStateError as exc:
            LOGGER.debug("Invalid state on future - probably duplicate response: %s", exc)

    @zigpy.util.retryable_request
    async def request(self, nwk, profile, cluster, src_ep, dst_ep, sequence, data, expect_reply=True, timeout=10):
        LOGGER.debug('request %s', (nwk, profile, cluster, src_ep, dst_ep, sequence, data, expect_reply, timeout))
        assert sequence not in self._pending
        send_fut = asyncio.Future()
        reply_fut = None
        if expect_reply:
            reply_fut = asyncio.Future()
        self._pending[sequence] = (send_fut, reply_fut)
        v, lqi = await self._api.raw_aps_data_request(nwk, src_ep, dst_ep, profile, cluster, data)
        self._zigate_seq[sequence] = v[1]

        if v[0] != 0:
            self._pending.pop(sequence)
            self._zigate_seq.pop(sequence)
            if expect_reply:
                reply_fut.cancel()
            raise DeliveryError("Message send failure %s" % (v[0], ))

        if expect_reply:
            # Wait for reply
            try:
                v = await asyncio.wait_for(reply_fut, timeout)
            except:  # noqa: E722
                # If we timeout (or fail for any reason), clear the future
                self._pending.pop(sequence)
                self._zigate_seq.pop(sequence)
                raise
        return v

    async def permit_ncp(self, time_s=60):
        assert 0 <= time_s <= 254
        await self._api.permit_join(time_s)

    async def broadcast(self, profile, cluster, src_ep, dst_ep, grpid, radius,
                        sequence, data, broadcast_address):
        LOGGER.debug("Broadcast not implemented.")
