import re
import os.path
import serial.tools.list_ports
import serial
import usb
import logging
import asyncio

LOGGER = logging.getLogger(__name__)


def discover_port():
    """ discover zigate port """
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
    return port


def is_pizigate(port):
    """ detect pizigate """
    # Suppose pizigate on /dev/ttyAMAx or /dev/serialx
    if port.startswith('pizigate:'):
        return True
    port = os.path.realpath(port)
    return re.match(r"/dev/(tty(S|AMA)|serial)\d+", port) is not None


def is_zigate_din(port):
    """ detect zigate din """
    port = os.path.realpath(port)
    if re.match(r"/dev/ttyUSB\d+", port):
        try:
            device = next(serial.tools.list_ports.grep(port))
            # Suppose zigate din /dev/ttyUSBx
            return device.description == 'ZiGate' and device.manufacturer == 'FTDI'
        except StopIteration:
            pass
    return False


def is_zigate_wifi(port):
    """ detect zigate din """
    return port.startswith('socket://')


async def set_pizigate_running_mode():
    try:
        import RPi.GPIO as GPIO
        LOGGER.info('Put PiZiGate in running mode')
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(17, GPIO.OUT)  # GPIO0
        GPIO.setup(27, GPIO.OUT)  # GPIO2
        GPIO.output(27, GPIO.HIGH)
        await asyncio.sleep(0.5)
        GPIO.output(17, GPIO.LOW)
        await asyncio.sleep(0.5)
        GPIO.output(17, GPIO.HIGH)
        await asyncio.sleep(0.5)
    except Exception as e:
        LOGGER.error('Unable to set PiZiGate GPIO, please check configuration')
        LOGGER.error(str(e))


async def set_pizigate_flashing_mode():
    try:
        import RPi.GPIO as GPIO
        LOGGER.info('Put PiZiGate in flashing mode')
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(17, GPIO.OUT)  # GPIO0
        GPIO.setup(27, GPIO.OUT)  # GPIO2
        GPIO.output(27, GPIO.LOW)
        await asyncio.sleep(0.5)
        GPIO.output(17, GPIO.LOW)
        await asyncio.sleep(0.5)
        GPIO.output(17, GPIO.HIGH)
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
