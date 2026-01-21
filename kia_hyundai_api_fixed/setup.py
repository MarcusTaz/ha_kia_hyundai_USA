"""Setup for kia-hyundai-api-fixed package."""
from setuptools import setup, find_packages

setup(
    name="kia-hyundai-api-fixed",
    version="2.0.0",
    description="Fixed Kia/Hyundai API with working OTP for USA",
    author="MarcusTaz",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "aiohttp>=3.8.0",
        "certifi>=2021.10.8",
        "pytz>=2021.3",
    ],
)
