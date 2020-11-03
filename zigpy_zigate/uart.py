import asyncio
import binascii
import logging
import struct
import re
import os.path
from typing import Any, Dict

import serial  # noqa
import serial.tools.list_ports
import serial_asyncio
import usb

from zigpy_zigate.config import CONF_DEVICE_PATH

LOGGER = logging.getLogger(__name__)
ZIGATE_BAUDRATE = 115200


class Gateway(asyncio.Protocol):
    START = b'\x01'
    END = b'\x03'

    def __init__(self, api, connected_future=None):
        self._buffer = b''
        self._connected_future = connected_future
        self._api = api

    def connection_made(self, transport):
        """Callback when the uart is connected"""
        LOGGER.debug("Connection made")
        self._transport = transport
        if self._connected_future:
            self._connected_future.set_result(True)

    def close(self):
        self._transport.close()

    def send(self, cmd, data=b''):
        """Send data, taking care of escaping and framing"""
        LOGGER.debug("Send: %s %s", hex(cmd), binascii.hexlify(data))
        length = len(data)
        byte_head = struct.pack('!HH', cmd, length)
        checksum = self._checksum(byte_head, data)
        frame = struct.pack('!HHB%ds' % length, cmd, length, checksum, data)
        LOGGER.debug('Frame to send: %s', frame)
        frame = self._escape(frame)
        LOGGER.debug('Frame escaped: %s', frame)
        self._transport.write(self.START + frame + self.END)

    def data_received(self, data):
        """Callback when there is data received from the uart"""
        self._buffer += data
#         LOGGER.debug('data_received %s', self._buffer)
        endpos = self._buffer.find(self.END)
        while endpos != -1:
            startpos = self._buffer.rfind(self.START, 0, endpos)
            if startpos != -1 and startpos < endpos:
                frame = self._buffer[startpos:endpos + 1]
                frame = self._unescape(frame[1:-1])
                cmd, length, checksum, f_data, lqi = struct.unpack('!HHB%dsB' % (len(frame) - 6), frame)
                if self._length(frame) != length:
                    LOGGER.warning("Invalid length: %s, data: %s",
                                   length,
                                   len(frame) - 6)
                    self._buffer = self._buffer[endpos + 1:]
                    continue
                if self._checksum(frame[:4], lqi, f_data) != checksum:
                    LOGGER.warning("Invalid checksum: %s, data: 0x%s",
                                   checksum,
                                   binascii.hexlify(frame).decode())
                    self._buffer = self._buffer[endpos + 1:]
                    continue
                LOGGER.debug("Frame received: %s", binascii.hexlify(frame).decode())
                self._api.data_received(cmd, f_data, lqi)
            else:
                LOGGER.warning('Malformed packet received, ignore it')
            self._buffer = self._buffer[endpos + 1:]
            endpos = self._buffer.find(self.END)

    def _unescape(self, data):
        flip = False
        ret = []
        for b in data:
            if flip:
                flip = False
                ret.append(b ^ 0x10)
            elif b == 0x02:
                flip = True
            else:
                ret.append(b)
        return bytes(ret)

    def _escape(self, data):
        ret = []
        for b in data:
            if b < 0x10:
                ret.extend([0x02, 0x10 ^ b])
            else:
                ret.append(b)
        return bytes(ret)

    def _checksum(self, *args):
        chcksum = 0
        for arg in args:
            if isinstance(arg, int):
                chcksum ^= arg
                continue
            for x in arg:
                chcksum ^= x
        return chcksum

    def _length(self, frame):
        length = len(frame) - 5
        return length


async def connect(device_config: Dict[str, Any], api, loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()

    connected_future = asyncio.Future()
    protocol = Gateway(api, connected_future)

    port = device_config[CONF_DEVICE_PATH]
    if port == 'auto':
        devices = list(serial.tools.list_ports.grep('ZiGate'))
        if devices:
            port = devices[0].device
            LOGGER.info('ZiGate found at %s', port)
        else:
            devices = list(serial.tools.list_ports.grep('067b:2303|CP2102'))
            if devices:
                port = devices[0].device
                LOGGER.info('ZiGate probably found at %s', port)
            else:
                LOGGER.error('Unable to find ZiGate using auto mode')
                raise serial.SerialException("Unable to find Zigate using auto mode")

    if port.startswith('socket://'):
        port = port.split('socket://', 1)[1]
        if ':' in port:
            host, port = port.split(':', 1)  # 192.168.x.y:9999
            port = int(port)
        else:
            host = port
            port = 9999
        _, protocol = await loop.create_connection(
            lambda: protocol,
            host, port)
    else:
        port = os.path.realpath(port)
        if re.match(r"/dev/(tty(S|AMA)|serial)\d+", port):
            # Suppose pizigate on /dev/ttyAMAx or /dev/serialx
            await set_pizigate_running_mode()
        if re.match(r"/dev/ttyUSB\d+", port):
            device = next(serial.tools.list_ports.grep(port))
            if device.manufacturer == 'FTDI':  # Suppose zigate din /dev/ttyUSBx
                await set_zigatedin_running_mode()

        _, protocol = await serial_asyncio.create_serial_connection(
            loop,
            lambda: protocol,
            url=port,
            baudrate=ZIGATE_BAUDRATE,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            xonxoff=False,
        )

    await connected_future

    return protocol


async def set_pizigate_running_mode():
    try:
        import RPi.GPIO as GPIO
        LOGGER.info('Put PiZiGate in running mode')
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(27, GPIO.OUT)  # GPIO2
        GPIO.output(27, GPIO.HIGH)  # GPIO2
        GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)  # GPIO0
        await asyncio.sleep(0.5)
        GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # GPIO0
        await asyncio.sleep(0.5)
    except Exception as e:
        LOGGER.error('Unable to set PiZiGate GPIO, please check configuration')
        LOGGER.error(str(e))


async def set_pizigate_flashing_mode():
    try:
        import RPi.GPIO as GPIO
        LOGGER.info('Put PiZiGate in flashing mode')
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(27, GPIO.OUT)  # GPIO2
        GPIO.output(27, GPIO.LOW)  # GPIO2
        GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)  # GPIO0
        await asyncio.sleep(0.5)
        GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # GPIO0
        await asyncio.sleep(0.5)
    except Exception as e:
        LOGGER.error('Unable to set PiZiGate GPIO, please check configuration')
        LOGGER.error(str(e))


def ftdi_set_bitmode(dev, bitmask):
    '''
    Set mode for ZiGate DIN module
    '''
    BITMODE_CBUS = 0x20
    SIO_SET_BITMODE_REQUEST = 0x0b
    bmRequestType = usb.util.build_request_type(usb.util.CTRL_OUT,
                                                usb.util.CTRL_TYPE_VENDOR,
                                                usb.util.CTRL_RECIPIENT_DEVICE)
    wValue = bitmask | (BITMODE_CBUS << BITMODE_CBUS)
    dev.ctrl_transfer(bmRequestType, SIO_SET_BITMODE_REQUEST, wValue)


async def set_zigatedin_running_mode():
    try:
        dev = usb.core.find(idVendor=0x0403, idProduct=0x6001)
        if not dev:
            LOGGER.error('ZiGate DIN not found.')
            return
        LOGGER.info('Put ZiGate DIN in running mode')
        ftdi_set_bitmode(dev, 0xC8)
        await asyncio.sleep(0.5)
        ftdi_set_bitmode(dev, 0xCC)
        await asyncio.sleep(0.5)
    except Exception as e:
        LOGGER.error('Unable to set FTDI bitmode, please check configuration')
        LOGGER.error(str(e))


async def set_zigatedin_flashing_mode():
    try:
        dev = usb.core.find(idVendor=0x0403, idProduct=0x6001)
        if not dev:
            LOGGER.error('ZiGate DIN not found.')
            return
        LOGGER.info('Put ZiGate DIN in flashing mode')
        ftdi_set_bitmode(dev, 0x00)
        await asyncio.sleep(0.5)
        ftdi_set_bitmode(dev, 0xCC)
        await asyncio.sleep(0.5)
        ftdi_set_bitmode(dev, 0xC0)
        await asyncio.sleep(0.5)
        ftdi_set_bitmode(dev, 0xC4)
        await asyncio.sleep(0.5)
        ftdi_set_bitmode(dev, 0xCC)
        await asyncio.sleep(0.5)
    except Exception as e:
        LOGGER.error('Unable to set FTDI bitmode, please check configuration')
        LOGGER.error(str(e))
