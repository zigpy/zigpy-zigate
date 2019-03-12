import asyncio
import logging
from binascii import unhexlify

from zigpy.exceptions import DeliveryError
import zigpy.application
import zigpy.util


LOGGER = logging.getLogger(__name__)


class ControllerApplication(zigpy.application.ControllerApplication):
    def __init__(self, zigate, database_file=None):
        super().__init__(database_file=database_file)
        self._zigate = zigate
        self._pending = {}
        self._zigate_seq = {}

    async def startup(self, auto_form=False):
        """Perform a complete application startup"""
        self._zigate.add_callback(self.zigate_callback_handler)
        self._zigate.autoStart()
        self._zigate.send_data(0x0002, '01')
        self._nwk = int(self._zigate.addr, 16)
        self._ieee = zigpy.application.t.EUI64(unhexlify(self._zigate.ieee))

    async def form_network(self, channel=15, pan_id=None, extended_pan_id=None):
        self._zigate.set_channel(channel)
#         if pan_id:
#             self._zigate.set_panid(pan_id)
        if extended_pan_id:
            self._zigate.set_extended_panid(extended_pan_id)

    async def force_remove(self, dev):
        self._zigate.remove_device_ieee(dev.ieee)

    def zigate_callback_handler(self, response):
        LOGGER.debug('zigate_callback_handler {}'.format(response))

        if response.msg == 0x8048:  # leave
            nwk = 0
            ieee = zigpy.application.t.EUI64(unhexlify(response['ieee']))
            self.handle_leave(nwk, ieee)
        elif response.msg == 0x004D:  # join
            nwk = int(response['addr'], 16)
            ieee = zigpy.application.t.EUI64(unhexlify(response['ieee']))
            parent_nwk = 0
            self.handle_join(nwk, ieee, parent_nwk)
        elif response.msg == 0x8002:
            nwk = int(response['source_address'], 16)
            try:
                device = self.get_device(nwk=nwk)
            except KeyError:
                LOGGER.debug("No such device %s", response['source_address'])
                return
            rssi = 0
            device.radio_details(response.lqi, rssi)
            tsn, command_id, is_reply, args = self.deserialize(device, response['source_endpoint'],
                                                               response['cluster_id'], response['payload'])
            if is_reply:
                self._handle_reply(device, response, tsn, command_id, args)
            else:
                self.handle_message(device, False, response['profile_id'],
                                    response['cluster_id'],
                                    response['source_endpoint'], response['destination_endpoint'],
                                    tsn, command_id, args)
        elif response.msg == 0x8702:  # APS Data confirm Fail
            self._handle_frame_failure(response['sequence'], response['status'])
#         elif frame_name == 'messageSentHandler':
#             if args[4] != t.EmberStatus.SUCCESS:
#                 self._handle_frame_failure(*args)
#             else:
#                 self._handle_frame_sent(*args)

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
#
#     def _handle_frame_sent(self, message_type, destination, aps_frame, message_tag, status, message):
#         try:
#             send_fut, reply_fut = self._pending[message_tag]
#             # Sometimes messageSendResult and a reply come out of order
#             # If we've already handled the reply, delete pending
#             if reply_fut is None or reply_fut.done():
#                 self._pending.pop(message_tag)
#             send_fut.set_result(True)
#         except KeyError:
#             LOGGER.warning("Unexpected message send notification")
#         except asyncio.futures.InvalidStateError as exc:
#             LOGGER.debug("Invalid state on future - probably duplicate response: %s", exc)

    @zigpy.util.retryable_request
    async def request(self, nwk, profile, cluster, src_ep, dst_ep, sequence, data, expect_reply=True, timeout=10):
        LOGGER.debug('request %s',(nwk, profile, cluster, src_ep, dst_ep, sequence, data, expect_reply, timeout))
        assert sequence not in self._pending
        send_fut = asyncio.Future()
        reply_fut = None
        if expect_reply:
            reply_fut = asyncio.Future()
        self._pending[sequence] = (send_fut, reply_fut)
        src_ep = 1
        v = self._zigate.raw_aps_data_request('{:04x}'.format(nwk), src_ep, dst_ep, profile, cluster, data[1:])
        self._zigate_seq[sequence] = v.sequence

        if v.status != 0:
            self._pending.pop(sequence)
            self._zigate_seq.pop(sequence)
            if expect_reply:
                reply_fut.cancel()
            raise DeliveryError("Message send failure %s" % (v.status, ))

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

    async def permit(self, time_s=60):
        assert 0 <= time_s <= 254
        self._zigate.permit_join(time_s)
