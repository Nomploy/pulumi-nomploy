"""Pulumi dynamic provider for nomploy (Python) — manage services as code over the REST API."""

from ._client import call, trigger
from .resources import (
    Application,
    Compose,
    Database,
    Domain,
    Mariadb,
    Mongo,
    Mysql,
    Postgres,
    Project,
    Redis,
)

__all__ = [
    "Project",
    "Application",
    "Domain",
    "Database",
    "Postgres",
    "Mysql",
    "Mariadb",
    "Mongo",
    "Redis",
    "Compose",
    "call",
    "trigger",
]
