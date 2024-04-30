'''Setup.'''
import os
from setuptools import setup, find_packages


setup(
    name='blue_naas',
    description='BlueNaaS (Neuron as a Service)',
    version=os.environ['VERSION'],
    url='https://blue-naas-bsp-epfl.apps.hbp.eu',
    author='Blue Brain Project, EPFL',
    install_requires=('uvicorn[standard]', 'fastapi', 'boto3', 'bluecellulab>=2.2.2,<3.0.0', 'requests'),
    packages=find_packages(exclude=[]),
    scripts=[],
)
