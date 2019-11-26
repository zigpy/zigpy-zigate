from unittest import mock

import pytest
import zigpy.types as zigpy_types

import zigpy_zigate.types as t
import zigpy_zigate.zigbee.application


@pytest.fixture
def app():
    api = mock.MagicMock()
    return zigpy_zigate.zigbee.application.ControllerApplication(api)


def test_zigpy_ieee(app):
    cluster = mock.MagicMock()
    cluster.cluster_id = 0x0000
    data = b'\x01\x02\x03\x04\x05\x06\x07\x08'

    zigate_ieee, _ = t.EUI64.deserialize(data)
    app._ieee = zigpy_types.EUI64(zigate_ieee)

    dst_addr = app.get_dst_address(cluster)
    assert dst_addr.serialize() == b'\x03' + data[::-1] + b'\x01'
