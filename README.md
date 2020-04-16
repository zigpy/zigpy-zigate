# zigpy-zigate

[![Build Status](https://travis-ci.com/zigpy/zigpy-zigate.svg?branch=master)](https://travis-ci.com/zigpy/zigpy-zigate)
[![Coverage](https://coveralls.io/repos/github/zigpy/zigpy-zigate/badge.svg?branch=master)](https://coveralls.io/github/zigpy/zigpy-zigate?branch=master)

**WARNING: EXPERIMENTAL! This project is under development as WIP (work in progress). Developer’s work provided “AS IS”.**

[zigpy-zigate](https://github.com/zigpy/zigpy-zigate) is a Python 3 implementation for the [Zigpy](https://github.com/zigpy/) project to implement [ZiGate](https://www.zigate.fr/) based [Zigbee](https://www.zigbee.org) radio devices.

- https://github.com/zigpy/zigpy-zigate

ZiGate is a open source ZigBee adapter hardware that was initially launched on Kickstarter by @fairecasoimeme

- https://www.zigate.fr
- https://www.kickstarter.com/projects/1361563794/zigate-universal-zigbee-gateway-for-smarthome

## Compatible hardware
The ZiGate USB adapter communicates via a PL-2303HX USB to Serial Bridge Controller module by Prolific. 
There's also a Wi-Fi adapter to communicate with ZiGate over network.

Note! ZiGate open source ZigBee adapter hardware requires ZiGate firmware 3.1a or later to work with this zigpy-zigate module.

### Known working Zigbee radio modules
- [ZiGate USB-TTL](https://zigate.fr/produit/zigate-ttl/)
- [ZiGate USB-DIN](https://zigate.fr/produit/zigate-usb-din/)
- [PiZiGate (ZiGate module for Raspberry Pi GPIO)](https://zigate.fr/produit/pizigate-v1-0/)

### Experimental Zigbee radio modules
- [ZiGate Pack WiFi](https://zigate.fr/produit/zigate-pack-wifi-v1-3/) (work in progress)

## Port configuration

- To configure __usb__ ZiGate port, just specify the port, example : `/dev/ttyUSB0`
    - Alternatively you could set port to `auto` to enable automatic usb port discovery
- To configure __pizigate__ port, prefix the port with `pizigate:`, example : `pizigate:/dev/serial0`
- To configure __wifi__ ZiGate, specify IP address and port, example : `socket://192.168.1.10:9999` 

Note! Requires ZiGate firmware 3.1a and later
- https://zigate.fr/tag/firmware/

## Testing new releases

Testing a new release of the zigpy-zigate library before it is released in Home Assistant.

If you are using Supervised Home Assistant (formerly known as the Hassio/Hass.io distro):
- Add https://github.com/home-assistant/hassio-addons-development as "add-on" repository
- Install "Custom deps deployment" addon
- Update config like: 
  ```
  pypi:
    - zigpy-zigate==0.5.1
  apk: []
  ```
  where 0.5.1 is the new version
- Start the addon

If you are instead using some custom python installation of Home Assistant then do this:
- Activate your python virtual env
- Update package with ``pip``
  ```
  pip install zigpy-zigate==0.5.1

## Releases via PyPI
Tagged versions are also released via PyPI

- https://pypi.org/project/zigpy-zigate/
- https://pypi.org/project/zigpy-zigate/#history
- https://pypi.org/project/zigpy-zigate/#files

## Developer references
Documents that layout the serial protocol used for ZiGate serial interface communication can be found here:

- https://github.com/fairecasoimeme/ZiGate/tree/master/Protocol

## How to contribute

If you are looking to make a contribution to this project we suggest that you follow the steps in these guides:
- https://github.com/firstcontributions/first-contributions/blob/master/README.md
- https://github.com/firstcontributions/first-contributions/blob/master/github-desktop-tutorial.md

Some developers might also be interested in receiving donations in the form of hardware such as Zigbee modules or devices, and even if such donations are most often donated with no strings attached it could in many cases help the developers motivation and indirect improve the development of this project.

## Related projects

### Zigpy
[Zigpy](https://github.com/zigpy/zigpy)** is **[Zigbee protocol stack](https://en.wikipedia.org/wiki/Zigbee)** integration project to implement the **[Zigbee Home Automation](https://www.zigbee.org/)** standard as a Python 3 library. Zigbee Home Automation integration with zigpy allows you to connect one of many off-the-shelf Zigbee adapters using one of the available Zigbee radio library modules compatible with zigpy to control Zigbee based devices. There is currently support for controlling Zigbee device types such as binary sensors (e.g., motion and door sensors), sensors (e.g., temperature sensors), lightbulbs, switches, and fans. A working implementation of zigbe exist in **[Home Assistant](https://www.home-assistant.io)** (Python based open source home automation software) as part of its **[ZHA component](https://www.home-assistant.io/components/zha/)**

### ZHA Device Handlers
ZHA deviation handling in Home Assistant relies on on the third-party [ZHA Device Handlers](https://github.com/dmulcahey/zha-device-handlers) project. Zigbee devices that deviate from or do not fully conform to the standard specifications set by the [Zigbee Alliance](https://www.zigbee.org) may require the development of custom [ZHA Device Handlers](https://github.com/dmulcahey/zha-device-handlers) (ZHA custom quirks handler implementation) to for all their functions to work properly with the ZHA component in Home Assistant. These ZHA Device Handlers for Home Assistant can thus be used to parse custom messages to and from non-compliant Zigbee devices. The custom quirks implementations for zigpy implemented as ZHA Device Handlers for Home Assistant are a similar concept to that of [Hub-connected Device Handlers for the SmartThings Classics platform](https://docs.smartthings.com/en/latest/device-type-developers-guide/) as well as that of [Zigbee-Shepherd Converters as used by Zigbee2mqtt](https://www.zigbee2mqtt.io/how_tos/how_to_support_new_devices.html), meaning they are each virtual representations of a physical device that expose additional functionality that is not provided out-of-the-box by the existing integration between these platforms.

### ZHA Map
Home Assistant can build ZHA network topology map using the [zha-map](https://github.com/zha-ng/zha-map) project.

### zha-network-visualization-card
[zha-network-visualization-card](https://github.com/dmulcahey/zha-network-visualization-card) is a custom Lovelace element for visualizing the ZHA Zigbee network in Home Assistant.

### ZHA Network Card
[zha-network-card](https://github.com/dmulcahey/zha-network-card) is a custom Lovelace card that displays ZHA network and device information in Home Assistant
