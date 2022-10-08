import enum
import zigpy.types


def deserialize(data, schema):
    result = []
    for type_ in schema:
        # value, data = type_.deserialize(data)
        if data:
            value, data = type_.deserialize(data)
        else:
            value = None
        result.append(value)
    return result, data


def serialize(data, schema):
    return b''.join(t(v).serialize() for t, v in zip(schema, data))


class Bytes(bytes):
    def serialize(self):
        return self

    @classmethod
    def deserialize(cls, data):
        return cls(data), b''


class LBytes(bytes):
    def serialize(self):
        return uint8_t(len(self)).serialize() + self

    @classmethod
    def deserialize(cls, data, byteorder='big'):
        _bytes = int.from_bytes(data[:1], byteorder)
        s = data[1:_bytes + 1]
        return s, data[_bytes + 1:]


class int_t(int):
    _signed = True
    _size = 0

    def serialize(self, byteorder='big'):
        return self.to_bytes(self._size, byteorder, signed=self._signed)

    @classmethod
    def deserialize(cls, data, byteorder='big'):
        # Work around https://bugs.python.org/issue23640
        r = cls(int.from_bytes(data[:cls._size],
                               byteorder, signed=cls._signed))
        data = data[cls._size:]
        return r, data


class int8s(int_t):
    _size = 1


class int16s(int_t):
    _size = 2


class int24s(int_t):
    _size = 3


class int32s(int_t):
    _size = 4


class int40s(int_t):
    _size = 5


class int48s(int_t):
    _size = 6


class int56s(int_t):
    _size = 7


class int64s(int_t):
    _size = 8


class uint_t(int_t):
    _signed = False


class uint8_t(uint_t):
    _size = 1


class uint16_t(uint_t):
    _size = 2


class uint24_t(uint_t):
    _size = 3


class uint32_t(uint_t):
    _size = 4


class uint40_t(uint_t):
    _size = 5


class uint48_t(uint_t):
    _size = 6


class uint56_t(uint_t):
    _size = 7


class uint64_t(uint_t):
    _size = 8


class EUI64(zigpy.types.EUI64):
    @classmethod
    def deserialize(cls, data):
        r, data = super().deserialize(data)
        return cls(r[::-1]), data

    def serialize(self):
        assert self._length == len(self)
        return super().serialize()[::-1]


class NWK(uint16_t):
    def __repr__(self):
        return "0x{:04x}".format(self)

    def __str__(self):
        return "0x{:04x}".format(self)


class AddressMode(uint8_t, enum.Enum):
    # Address modes used in zigate protocol

    BOUND = 0x00
    GROUP = 0x01
    NWK = 0x02
    IEEE = 0x03
    BROADCAST = 0x04

    NO_TRANSMIT = 0x05

    BOUND_NO_ACK = 0x06
    NWK_NO_ACK = 0x07
    IEEE_NO_ACK = 0x08

    BOUND_NON_BLOCKING = 0x09
    BOUND_NON_BLOCKING_NO_ACK = 0x0A


class Status(uint8_t, enum.Enum):
    Success = 0x00
    IncorrectParams = 0x01
    UnhandledCommand = 0x02
    CommandFailed = 0x03
    Busy = 0x04
    StackAlreadyStarted = 0x05

    # Errors below are due to resource shortage, retrying may succeed OR There are no
    # free Network PDUs. The number of NPDUs is set in the “Number of NPDUs” property
    # of the “PDU Manager” section of the config editor
    ResourceShortage = 0x80
    # There are no free Application PDUs. The number of APDUs is set in the “Instances”
    # property of the appropriate “APDU” child of the “PDU Manager” section of the
    # config editor
    NoFreeAppPDUs = 0x81
    # There are no free simultaneous data request handles. The number of handles is set
    # in the “Maximum Number of Simultaneous Data Requests” field of the “APS layer
    # configuration” section of the config editor
    NoFreeDataReqHandles = 0x82
    # There are no free APS acknowledgement handles. The number of handles is set in
    # the “Maximum Number of Simultaneous Data Requests with Acks” field of the “APS
    # layer configuration” section of the config editor
    NoFreeAPSAckHandles = 0x83
    # There are no free fragment record handles. The number of handles is set in
    # the “Maximum Number of Transmitted Simultaneous Fragmented Messages” field of
    # the “APS layer configuration” section of the config editor
    NoFreeFragRecHandles = 0x84
    # There are no free MCPS request descriptors. There are 8 MCPS request descriptors.
    # These are only ever likely to be exhausted under very heavy network load or when
    # trying to transmit too many frames too close together.
    NoFreeMCPSReqDesc = 0x85
    # The loop back send is currently busy. There can be only one loopback request at a
    # time.
    LoopbackSendBusy = 0x86
    # There are no free entries in the extended address table. The extended address
    # table is configured in the config editor
    NoFreeExtAddrTableEntries = 0x87
    # The simple descriptor does not exist for this endpoint / cluster.
    SimpleDescDoesNotExist = 0x88
    # A bad parameter has been found while processing an APSDE request or response
    BadAPSDEParam = 0x89
    # No free Routing table entries left
    NoFreeRoutingTableEntries = 0x8A
    # No free BTR entries left.
    NoFreeBTREntries = 0x8B

    # A transmit request failed since the ASDU is too large and fragmentation is not
    # supported.
    AsduTooLong = 0xA0
    # A received fragmented frame could not be defragmented at the current time.
    DefragDeferred = 0xA1
    # A received fragmented frame could not be defragmented since the device does not
    # support fragmentation.
    DefragUnsupported = 0xA2
    # A parameter value was out of range.
    IllegalRequest = 0xA3
    # An APSME-UNBIND.request failed due to the requested binding link not existing in
    # the binding table.
    InvalidBinding = 0xA4
    # An APSME-REMOVE-GROUP.request has been issued with a group identifier that does
    # not appear in the group table.
    InvalidGroup = 0xA5
    # A parameter value was invalid or out of range.
    InvalidParameter = 0xA6
    # An APSDE-DATA.request requesting acknowledged transmission failed due to no
    # acknowledgement being received.
    NoAck = 0xA7
    # An APSDE-DATA.request with a destination addressing mode set to 0x00 failed due to
    # there being no devices bound to this device.
    NoBoundDevice = 0xA8
    # An APSDE-DATA.request with a destination addressing mode set to 0x03 failed due to
    # no corresponding short address found in the address map table.
    NoShortAddress = 0xA9
    # An APSDE-DATA.request with a destination addressing mode set to 0x00 failed due to
    # a binding table not being supported on the device.
    NotSupported = 0xAA
    # An ASDU was received that was secured using a link key.
    SecuredLinkKey = 0xAB
    # An ASDU was received that was secured using a network key.
    SecuredNwkKey = 0xAC
    # An APSDE-DATA.request requesting security has resulted in an error during the
    # corresponding security processing.
    SecurityFail = 0xAD
    # An APSME-BIND.request or APSME.ADDGROUP.request issued when the binding or group
    # tables, respectively, were full.
    TableFull = 0xAE
    # An ASDU was received without any security.
    Unsecured = 0xAF
    # An APSME-GET.request or APSMESET. request has been issued with an unknown
    # attribute identifier.
    UnsupportedAttribute = 0xB0

    @classmethod
    def _missing_(cls, value):
        if not isinstance(value, int):
            raise ValueError(f"{value} is not a valid {cls.__name__}")

        new_member = cls._member_type_.__new__(cls, value)
        new_member._name_ = f"unknown_0x{value:02X}"
        new_member._value_ = cls._member_type_(value)

        return new_member


class LogLevel(uint8_t, enum.Enum):
    Emergency = 0
    Alert = 1
    Critical = 2
    Error = 3
    Warning = 4
    Notice = 5
    Information = 6
    Debug = 7


class Struct:
    _fields = []

    def __init__(self, *args, **kwargs):
        if len(args) == 1 and isinstance(args[0], self.__class__):
            # copy constructor
            for field in self._fields:
                if hasattr(args[0], field[0]):
                    setattr(self, field[0], getattr(args[0], field[0]))
        elif len(args) == len(self._fields):
            for arg, field in zip(args, self._fields):
                setattr(self, field[0], field[1](arg))
        elif kwargs:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def serialize(self):
        r = b''
        for field in self._fields:
            if hasattr(self, field[0]):
                r += getattr(self, field[0]).serialize()
        return r

    @classmethod
    def deserialize(cls, data):
        r = cls()
        for field_name, field_type in cls._fields:
            v, data = field_type.deserialize(data)
            setattr(r, field_name, v)
        return r, data

    def __repr__(self):
        r = '<%s ' % (self.__class__.__name__, )
        r += ' '.join(
            ['%s=%s' % (f[0], getattr(self, f[0], None)) for f in self._fields]
        )
        r += '>'
        return r


ZIGPY_TO_ZIGATE_ADDR_MODE = {
    # With ACKs
    (zigpy.types.AddrMode.NWK, True): AddressMode.NWK,
    (zigpy.types.AddrMode.IEEE, True): AddressMode.IEEE,
    (zigpy.types.AddrMode.Broadcast, True): AddressMode.BROADCAST,
    (zigpy.types.AddrMode.Group, True): AddressMode.GROUP,

    # Without ACKs
    (zigpy.types.AddrMode.NWK, False): AddressMode.NWK_NO_ACK,
    (zigpy.types.AddrMode.IEEE, False): AddressMode.IEEE_NO_ACK,
    (zigpy.types.AddrMode.Broadcast, False): AddressMode.BROADCAST,
    (zigpy.types.AddrMode.Group, False): AddressMode.GROUP,
}

ZIGATE_TO_ZIGPY_ADDR_MODE = {
    zigate_addr: (zigpy_addr, ack)
    for (zigpy_addr, ack), zigate_addr in ZIGPY_TO_ZIGATE_ADDR_MODE.items()
}


class Address(Struct):
    _fields = [
        ('address_mode', AddressMode),
        ('address', EUI64),
    ]

    def __eq__(self, other):
        return other.address_mode == self.address_mode and other.address == self.address

    @classmethod
    def deserialize(cls, data):
        r = cls()
        r.address_mode, data = AddressMode.deserialize(data)

        if r.address_mode in (AddressMode.IEEE, AddressMode.IEEE_NO_ACK):
            r.address, data = EUI64.deserialize(data)
        else:
            r.address, data = NWK.deserialize(data)

        return r, data

    def to_zigpy_type(self):
        zigpy_addr_mode, ack = ZIGATE_TO_ZIGPY_ADDR_MODE[self.address_mode]

        return (
            zigpy.types.AddrModeAddress(addr_mode=zigpy_addr_mode, address=self.address),
            ack,
        )


class DeviceEntry(Struct):
    _fields = [
        ("id", uint8_t),
        ("short_addr", NWK),
        ("ieee_addr", EUI64),
        ("power_source", uint8_t),
        ("link_quality", uint8_t),
    ]


class DeviceEntryArray(tuple):
    @classmethod
    def deserialize(cls, data):
        if len(data) % 13 != 0:
            raise ValueError("Data is not an array of DeviceEntry")

        entries = []

        while data:
            entry, data = DeviceEntry.deserialize(data)
            entries.append(entry)

        return cls(entries), data

    def serialize(self):
        return b"".join([e.serialize() for e in self])
