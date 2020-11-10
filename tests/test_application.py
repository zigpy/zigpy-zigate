from unittest import mock

import pytest
import zigpy.types as zigpy_types

import zigpy_zigate.config as config
import zigpy_zigate.types as t
import zigpy_zigate.zigbee.application

APP_CONFIG = zigpy_zigate.zigbee.application.ControllerApplication.SCHEMA(
    {
        config.CONF_DEVICE: {config.CONF_DEVICE_PATH: "/dev/null"},
        config.CONF_DATABASE: None,
    }
)
FAKE_FIRMWARE_VERSION = '3.1z'

@pytest.fixture
def app():
    a = zigpy_zigate.zigbee.application.ControllerApplication(APP_CONFIG)
    a.version = FAKE_FIRMWARE_VERSION
    return a


def test_zigpy_ieee(app):
    cluster = mock.MagicMock()
    cluster.cluster_id = 0x0000
    data = b"\x01\x02\x03\x04\x05\x06\x07\x08"

    zigate_ieee, _ = t.EUI64.deserialize(data)
    app._ieee = zigpy_types.EUI64(zigate_ieee)

    dst_addr = app.get_dst_address(cluster)
    assert dst_addr.serialize() == b"\x03" + data[::-1] + b"\x01"


def test_model_detection(app):
    device = zigpy_zigate.zigbee.application.ZiGateDevice(app, 0, 0)
    assert device.model == 'ZiGate USB-TTL {}'.format(FAKE_FIRMWARE_VERSION)
