"""Setup module for zigpy-zigate"""

import pathlib

from setuptools import find_packages, setup
from zigpy_zigate import __version__

setup(
    name="zigpy-zigate",
    version=__version__,
    description="A library which communicates with ZiGate radios for zigpy",
    long_description=(pathlib.Path(__file__).parent / "README.md").read_text(),
    long_description_content_type="text/markdown",
    url="http://github.com/zigpy/zigpy-zigate",
    author="Sébastien RAMAGE",
    author_email="sebatien.ramage@gmail.com",
    license="GPL-3.0",
    packages=find_packages(exclude=['tests']),
    install_requires=[
        'pyserial>=3.5',
        'pyserial-asyncio>=0.5; platform_system!="Windows"',
        'pyserial-asyncio!=0.5; platform_system=="Windows"',  # 0.5 broke writes
        'pyusb>=1.1.0',
        'zigpy>=0.51.0',
        'gpiozero',
    ],
    tests_require=[
        'pytest',
        'pytest-asyncio',
        'mock'
    ],
)
