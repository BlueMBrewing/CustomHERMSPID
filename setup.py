from setuptools import setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="cbpi4-PIDHermsMashDelta",
    version="0.1.0",
    description="CraftBeerPi4 HERMS Kettle Logic: Mash-sensor PID with HLT/Mash delta safety cutoff",
    author="Your Name",
    author_email="you@example.com",
    url="https://github.com/yourname/cbpi4-PIDHermsMashDelta",
    include_package_data=True,
    package_data={
        "": ["*.txt", "*.rst", "*.yaml"],
        "cbpi4-PIDHermsMashDelta": ["*", "*.txt", "*.rst", "*.yaml"],
    },
    packages=["cbpi4-PIDHermsMashDelta"],
    long_description=long_description,
    long_description_content_type="text/markdown",
    python_requires=">=3.9,<3.12",
)
