import logging
import zigate

LOGGER = logging.getLogger(__name__)


class ZiGate:
    def __init__(self):
        self._zigate = None

    async def connect(self, device, baudrate=115200):
        self._zigate = zigate.ZiGate(device, auto_start=False)

    def __getattr__(self, name):
        return self._zigate.__getattribute__(name)

    def close(self):
        return self._zigate.close()

    def set_application(self, app):
        self._app = app
