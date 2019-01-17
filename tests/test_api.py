from unittest import mock

import pytest

from zigpy_zigate import api as zigate_api


@pytest.fixture
def api():
    api = zigate_api.ZiGate()
    api._zigate = mock.MagicMock()
    return api


def test_set_application(api):
    api.set_application(mock.sentinel.app)
    assert api._app == mock.sentinel.app


def test_connect(monkeypatch):
    api = zigate_api.ZiGate()
    api.connect('dummy', 115200)


def test_close(api):
    api._zigate.close = mock.MagicMock()
    api.close()
    assert api._zigate.close.call_count == 1
