# zigpy-zigate

[![Build Status](https://travis-ci.org/doudz/zigpy-zigate.svg?branch=master)](https://travis-ci.org/doudz/zigpy-zigate)
[![Coverage](https://coveralls.io/repos/github/doudz/zigpy-zigate/badge.svg?branch=master)](https://coveralls.io/github/doudz/zigpy-zigate?branch=master)

[zigpy-zigate](https://github.com/doudz/zigpy-zigate) is a Python 3 implementation for the [Zigpy](https://github.com/zigpy/) project to implement [ZiGate](https://www.zigate.fr/) based [Zigbee](https://www.zigbee.org) radio devices.

- https://github.com/doudz/zigpy-zigate

ZiGate is a open source ZigBee adapter hardware that was initially launched on Kickstarter by @fairecasoimeme

- https://www.zigate.fr
- https://www.kickstarter.com/projects/1361563794/zigate-universal-zigbee-gateway-for-smarthome

The Zigate adapter communicates via a PL-2303HX USB to Serial Bridge Controller module by Prolific. 
There's also a wifi adapter to communicate with ZiGate over network.

Documents that layout the serial protocol used for ZiGate serial interface communication can be found here:

- https://github.com/fairecasoimeme/ZiGate/tree/master/Protocol

# WARNING : EXPERIMENTAL

Require the zigate firmware 3.1a and later
https://zigate.fr/tag/firmware/
