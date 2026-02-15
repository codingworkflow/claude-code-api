#!/usr/bin/env python
"""Setup script for claude-code-api package."""

import os
from setuptools import setup, find_packages

setup(
    name="claude-code-api",
    version="1.0.0",
    description="OpenAI-compatible API gateway for Claude Code with streaming support",
    long_description=open("README.md").read() if os.path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Claude Code API Team",
    url="https://github.com/claude-code-api/claude-code-api",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.32.0",
        "pydantic>=2.9.0",
        "httpx>=0.25.0",
        "aiofiles>=23.2.1",
        "structlog>=23.2.0",
        "python-multipart>=0.0.6",
        "pydantic-settings>=2.1.0",
        "sqlalchemy>=2.0.23",
        "greenlet>=3.0.0",
        "aiosqlite>=0.19.0",
        "alembic>=1.13.0",
        "passlib[bcrypt]>=1.7.4",
        "python-jose[cryptography]>=3.3.0",
        "python-dotenv>=1.0.0",
    ],
    extras_require={
        "test": [
            "pytest>=7.4.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.1.0",
            "httpx>=0.25.0",
            "requests>=2.31.0",
            "pytest-mock>=3.12.0",
        ],
        "dev": [
            "black>=23.0.0",
            "isort>=5.12.0",
            "flake8>=6.0.0",
            "mypy>=1.7.0",
            "pre-commit>=3.5.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "claude-code-api=claude_code_api.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Internet :: WWW/HTTP :: HTTP Servers",
    ],
)
