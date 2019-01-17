"""Setup module for zigpy-zigate"""

from setuptools import find_packages, setup

setup(
    name="zigpy-zigate",
    version="0.0.1",
    description="A library which communicates with ZiGate radios for zigpy",
    url="http://github.com/doudz/zigpy-zigate",
    author="Sébastien RAMAGE",
    author_email="sebatien.ramage@gmail.com",
    license="GPL-3.0",
    packages=find_packages(exclude=['*.tests']),
    install_requires=[
        'zigate',
    ],
    tests_require=[
        'pytest',
    ],
)
