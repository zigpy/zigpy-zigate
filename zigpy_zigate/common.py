import re
import time
import os.path
import serial.tools.list_ports
import serial
import logging
import asyncio

from gpiozero import OutputDevice


LOGGER = logging.getLogger(__name__)

GPIO_PIN0 = 17
GPIO_PIN2 = 27


class UnclosableOutputDevice(OutputDevice):
    """
    `OutputDevice` that never closes its pins. Allows for the last-written pin state to
    be retained even after the `OutputDevice` is garbage collected.
    """

    def __init__(
        self, pin=None, *, active_high=True, initial_value=False, pin_factory=None
    ):
        super().__init__(
            pin,
            active_high=active_high,
            initial_value=initial_value,
            pin_factory=pin_factory,
        )
        self._pin.close = lambda *args, **kwargs: None
        self.pin_factory.close = lambda *args, **kwargs: None


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


def set_pizigate_running_mode():
    LOGGER.info('Put PiZiGate in running mode')

    gpio0 = UnclosableOutputDevice(pin=GPIO_PIN0, initial_value=None)
    gpio2 = UnclosableOutputDevice(pin=GPIO_PIN2, initial_value=None)

    gpio2.on()
    time.sleep(0.5)

    gpio0.off()
    time.sleep(0.5)

    gpio0.on()
    time.sleep(0.5)


def set_pizigate_flashing_mode():
    LOGGER.info('Put PiZiGate in flashing mode')

    gpio0 = UnclosableOutputDevice(pin=GPIO_PIN0, initial_value=None)
    gpio2 = UnclosableOutputDevice(pin=GPIO_PIN2, initial_value=None)

    gpio2.off()
    time.sleep(0.5)

    gpio0.off()
    time.sleep(0.5)

    gpio0.on()
    time.sleep(0.5)


def ftdi_set_bitmode(dev, bitmask):
    '''
    Set mode for ZiGate DIN module
    '''
    import usb

    BITMODE_CBUS = 0x20
    SIO_SET_BITMODE_REQUEST = 0x0b
    bmRequestType = usb.util.build_request_type(usb.util.CTRL_OUT,
                                                usb.util.CTRL_TYPE_VENDOR,
                                                usb.util.CTRL_RECIPIENT_DEVICE)
    wValue = bitmask | (BITMODE_CBUS << BITMODE_CBUS)
    dev.ctrl_transfer(bmRequestType, SIO_SET_BITMODE_REQUEST, wValue)


def set_zigatedin_running_mode():
    import usb

    dev = usb.core.find(idVendor=0x0403, idProduct=0x6001)
    if not dev:
        raise RuntimeError('ZiGate DIN not found.')

    LOGGER.info('Put ZiGate DIN in running mode')
    ftdi_set_bitmode(dev, 0xC8)
    time.sleep(0.5)
    ftdi_set_bitmode(dev, 0xCC)
    time.sleep(0.5)


def set_zigatedin_flashing_mode():
    import usb

    dev = usb.core.find(idVendor=0x0403, idProduct=0x6001)
    if not dev:
        raise RuntimeError('ZiGate DIN not found.')

    LOGGER.info('Put ZiGate DIN in flashing mode')
    ftdi_set_bitmode(dev, 0x00)
    time.sleep(0.5)
    ftdi_set_bitmode(dev, 0xCC)
    time.sleep(0.5)
    ftdi_set_bitmode(dev, 0xC0)
    time.sleep(0.5)
    ftdi_set_bitmode(dev, 0xC4)
    time.sleep(0.5)
    ftdi_set_bitmode(dev, 0xCC)
    time.sleep(0.5)


def async_run_in_executor(function):
    """Decorator to make a sync function async."""

    async def replacement(*args):
        return asyncio.get_running_loop().run_in_executor(None, function, *args)

    replacement._sync_func = function

    return replacement


# Create async version of all of the above functions
async_set_pizigate_running_mode = async_run_in_executor(set_pizigate_running_mode)
async_set_pizigate_flashing_mode = async_run_in_executor(set_pizigate_flashing_mode)
async_set_zigatedin_running_mode = async_run_in_executor(set_zigatedin_running_mode)
async_set_zigatedin_flashing_mode = async_run_in_executor(set_zigatedin_flashing_mode)