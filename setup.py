from setuptools import setup, find_packages

setup(
    name="agentspec",
    version="0.4.0",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "aspec=agentspec.cli:main",
        ],
    },
)
