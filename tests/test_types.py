import binascii

from zigpy_zigate import types as t
from zigpy_zigate.api import COMMANDS, RESPONSES


def test_deserialize():
    extra = b"\xBE\xEF"
    data = b"\x00\x01\x00\x02"
    schema = RESPONSES[0x8000]
    result, rest = t.deserialize(data + extra, schema)
    assert rest == b""
    assert result[0] == 0x00
    assert result[1] == 0x01
    assert result[2] == 0x0002
    assert result[3] == extra

    extra = b"\xBE\xEF"
    data = b"\x00\x00\x01\x00\x01\x01\x01\x02\x12\x34\x02\xab\xcd\x01\x00"
    schema = RESPONSES[0x8002]
    result, rest = t.deserialize(data + extra, schema)
    assert result[0] == 0x00
    assert result[1] == 0x0001
    assert result[2] == 0x0001
    assert result[3] == 0x01
    assert result[4] == 0x01
    assert result[5] == t.Address(address_mode=t.AddressMode.NWK, address=t.NWK(0x1234))
    assert result[6] == t.Address(address_mode=t.AddressMode.NWK, address=t.NWK(0xABCD))
    assert result[7] == b"\x01\x00\xBE\xEF"
    assert rest == b""

    data = b"\x00\x01\x01\x02\x12\x34\xff"
    schema = RESPONSES[0x8702]
    result, rest = t.deserialize(data + extra, schema)
    assert result[0] == 0x00
    assert result[1] == 0x01
    assert result[2] == 0x01
    assert result[3] == t.Address(address_mode=t.AddressMode.NWK, address=t.NWK(0x1234))
    assert result[4] == 0xFF

    data = b"\x00\x01\x01\x03\x12\x34\x56\x78\x9a\xbc\xde\xf0\xff"
    schema = RESPONSES[0x8702]
    result, rest = t.deserialize(data + extra, schema)
    assert result[0] == 0x00
    assert result[1] == 0x01
    assert result[2] == 0x01
    assert result[3] == t.Address(
        address_mode=t.AddressMode.IEEE,
        address=t.EUI64.deserialize(b"\x12\x34\x56\x78\x9a\xbc\xde\xf0")[0],
    )
    assert result[4] == 0xFF

    data = b"\x00\x01\x01\x12\x34\x56\x78\x9a\xbc\xde\xf0\xff"
    schema = RESPONSES[0x8024]
    result, rest = t.deserialize(data, schema)
    assert result[0] == 0x00
    assert result[1] == 0x0101
    assert result[2] == t.EUI64.deserialize(b"\x12\x34\x56\x78\x9a\xbc\xde\xf0")[0]
    assert result[3] == 0xFF

    data = b"\x06"
    schema = RESPONSES[0x8024]
    result, rest = t.deserialize(data, schema)
    assert result[0] == 0x06
    assert result[1] is None
    assert result[2] is None
    assert result[3] is None
    assert len(result) == 4

    # Frame received: 8012000a2800010102bc8c73000100
    # data received 0x8012 b'00010102bc8c730001'

    data = binascii.unhexlify(b"00010102bc8c730001")
    schema = RESPONSES[0x8012]
    result, rest = t.deserialize(data, schema)
    assert result[0] == 0x00
    assert result[1] == 0x01
    assert result[2] == 0x01
    assert result[3] == t.Address(
        address_mode=t.AddressMode.NWK, address=t.NWK.deserialize(b"\xbc\x8c")[0]
    )
    assert result[4] == 0x73
    assert len(result) == 5

    # Frame received: 99990002828000
    # data received 0x9999 b'80' LQI:0

    data = binascii.unhexlify(b"80")
    schema = RESPONSES[0x9999]
    result, rest = t.deserialize(data, schema)
    assert result[0] == 0x80
    assert len(result) == 1


def test_serialize():
    data = [True]
    schema = COMMANDS[0x0002]
    result = t.serialize(data, schema)
    assert result == b"\x01"

    data = [b"\x12\x34"]
    schema = (t.LBytes,)
    result = t.serialize(data, schema)
    assert result == b"\x02\x124"


def test_EUI64():
    data = b"\x12\x34\x56\x78\x9a\xbc\xde\xf0\x00"
    ieee, rest = t.EUI64.deserialize(data)
    assert rest == b"\x00"
    assert ieee == t.EUI64.deserialize(b"\x12\x34\x56\x78\x9a\xbc\xde\xf0")[0]
    data2 = ieee.serialize()
    assert data2 == b"\x12\x34\x56\x78\x9a\xbc\xde\xf0"
    assert str(ieee) == "12:34:56:78:9a:bc:de:f0"


def test_NWK():
    data = b"\x124"
    nwk, rest = t.NWK.deserialize(data)
    assert nwk == t.NWK(0x1234)
    data2 = nwk.serialize()
    assert data2 == data
    assert repr(nwk) == "0x1234"
