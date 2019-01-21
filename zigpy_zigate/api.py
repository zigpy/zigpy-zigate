import logging
import zigate

LOGGER = logging.getLogger(__name__)


class ZiGate:
    def __init__(self):
        self._zigate = None

    def connect(self, device, baudrate=115200):
        assert self._zigate is None
        if '.' in device:  # supposed I.P:PORT
            host_port = device.split(':', 1)
            host = host_port[0]
            port = None
            if len(host_port) == 2:
                port = int(host_port[1])
            LOGGER.info('Configuring ZiGate WiFi {} {}'.format(host, port))
            self._zigate = zigate.ZiGateWiFi(host, port, auto_start=False)
        else:
            LOGGER.info('Configuring ZiGate USB {}'.format(device))
            self._zigate = zigate.ZiGate(device, auto_start=False)

    def __getattr__(self, name):
        return self._zigate.__getattribute__(name)

    def close(self):
        return self._zigate.close()

    def set_application(self, app):
        self._app = app
