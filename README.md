# zigpy-zigate

[![Build Status](https://travis-ci.com/doudz/zigpy-zigate.svg?branch=master)](https://travis-ci.com/doudz/zigpy-zigate)
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

# Releases via PyPI
Tagged versions are also released via PyPI

- https://pypi.org/project/zigpy-zigate/
- https://pypi.org/project/zigpy-zigate/#history
- https://pypi.org/project/zigpy-zigate/#files

# Port configuration

- To configure __usb__ ZiGate port, just specify the port, example : `/dev/ttyUSB0`
    - Alternatively you could set port to `auto` to enable automatic usb port discovery
- To configure __pizigate__ port, prefix the port with `pizigate:`, example : `pizigate:/dev/serial0`
- To configure __wifi__ ZiGate, specify IP address and port, example : `socket://192.168.1.10:9999` 

# WARNING : EXPERIMENTAL

Require the zigate firmware 3.1a and later
https://zigate.fr/tag/firmware/

# How to contribute

If you are looking to make a contribution to this project we suggest that you follow the steps in these guides:
- https://github.com/firstcontributions/first-contributions/blob/master/README.md
- https://github.com/firstcontributions/first-contributions/blob/master/github-desktop-tutorial.md

Some developers might also be interested in receiving donations in the form of hardware such as Zigbee modules or devices, and even if such donations are most often donated with no strings attached it could in many cases help the developers motivation and indirect improve the development of this project.

# Comment contribuer

Si vous souhaitez apporter une contribution à ce projet, nous vous suggérons de suivre les étapes décrites dans ces guides:
- https://github.com/firstcontributions/first-contributions/blob/master/README.md
- https://github.com/firstcontributions/first-contributions/blob/master/github-desktop-tutorial.md

Certains développeurs pourraient également être intéressés par des dons sous forme de matériel, tels que des modules ou des dispositifs Zigbee, et même si ces dons sont le plus souvent donnés sans aucune condition, cela pourrait dans de nombreux cas motiver les développeurs et indirectement améliorer le développement de ce projet.
