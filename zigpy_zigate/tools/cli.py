"""
 Simple CLI ZiGate tool
"""

import argparse
import asyncio
import logging
from os import wait
from zigpy_zigate.api import LOGGER, ZiGate, NoResponseError, CommandError
import zigpy_zigate.config


async def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("command", help="Command to start",
                        choices=["version", "reset", "erase_persistent",
                                 "set_time", "get_time", "set_led", "set_certification", "set_tx_power", "management_network_request",
                                 "loop"])
    parser.add_argument("-p", "--port", help="Port", default='auto')
    parser.add_argument("-d", "--debug", help="Debug log", action='store_true')
    parser.add_argument("-v", "--value", help="Set command's value")
    args = parser.parse_args()
    print('Port set to', args.port)
    if args.debug:
        logging.root.setLevel(logging.DEBUG)
    device_config = {zigpy_zigate.config.CONF_DEVICE_PATH: args.port}
    api = ZiGate(device_config)
    await api.connect()
    if args.command == 'version':
        print('Firmware version', await api.version_str())
    elif args.command == 'reset':
        await api.reset()
        print('ZiGate reseted')
    elif args.command == 'erase_persistent':
        await api.erase_persistent_data()
        print('ZiGate pesistent date erased')
    elif args.command == 'set_time':
        await api.set_time()
        print('ZiGate internal time server set to current time')
    elif args.command == 'get_time':
        print('ZiGate internal time server is', await api.get_time_server())
    elif args.command == 'set_led':
        enable = int(args.value or 1)
        print('Set ZiGate led to', enable)
        await api.set_led(enable)
    elif args.command == 'set_certification':
        _type = args.value or 'CE'
        print('Set ZiGate Certification to', _type)
        await api.set_certification(_type)
    elif args.command == 'set_tx_power':
        power = int(args.value or 63)
        print('Set ZiGate TX Power to', power)
        print('Tx power set to', await api.set_tx_power(power))
    elif args.command == 'management_network_request':
        await api.reset()
        # await api.set_raw_mode(False)
        await api.management_network_request()
        print('ok')
        await asyncio.sleep(10)
    elif args.command == 'loop':  # for testing purpose
        enable = True

        while True:
            try:
                LOGGER.info('Set led %s', enable)
                await api.set_led(enable)
                enable = not enable
                await asyncio.sleep(1)
            except KeyboardInterrupt:
                break
            except (NoResponseError, CommandError):
                LOGGER.exception('NoResponseError')
                await asyncio.sleep(1)
                continue
    api.close()

if __name__ == '__main__':
    asyncio.run(main())
