"""Setup module for zigpy-zigate"""
import os

from setuptools import find_packages, setup
from zigpy_zigate import __version__


# extracted from https://raspberrypi.stackexchange.com/questions/5100/detect-that-a-python-program-is-running-on-the-pi
def is_raspberry_pi(raise_on_errors=False):
    """Checks if Raspberry PI.

    :return:
    """
    try:
        with open('/proc/cpuinfo', 'r') as cpuinfo:
            found = False
            for line in cpuinfo:
                if line.startswith('Hardware'):
                    found = True
                    label, value = line.strip().split(':', 1)
                    value = value.strip()
                    if value not in (
                        'BCM2708',
                        'BCM2709',
                        'BCM2835',
                        'BCM2836'
                    ):
                        if raise_on_errors:
                            raise ValueError(
                                'This system does not appear to be a '
                                'Raspberry Pi.'
                            )
                        else:
                            return False
            if not found:
                if raise_on_errors:
                    raise ValueError(
                        'Unable to determine if this system is a Raspberry Pi.'
                    )
                else:
                    return False
    except IOError:
        if raise_on_errors:
            raise ValueError('Unable to open `/proc/cpuinfo`.')
        else:
            return False

    return True


requires = [
    'pyserial-asyncio',
    'pyusb',
    'zigpy>=0.22.2',
]

if is_raspberry_pi():
    requires.append('RPi.GPIO')

this_directory = os.path.join(os.path.abspath(os.path.dirname(__file__)))
with open(os.path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="zigpy-zigate",
    version=__version__,
    description="A library which communicates with ZiGate radios for zigpy",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="http://github.com/zigpy/zigpy-zigate",
    author="Sébastien RAMAGE",
    author_email="sebatien.ramage@gmail.com",
    license="GPL-3.0",
    packages=find_packages(exclude=['tests']),
    install_requires=requires,
    tests_require=[
        'pytest',
        'pytest-asyncio',
        'mock'
    ],
)
