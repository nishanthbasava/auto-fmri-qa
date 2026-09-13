"""Run Alembic migrations programmatically (`autoqa db upgrade`).

Migrations ship inside the package (autoqa/db/migrations) so the Docker image
and the installed wheel can migrate without the repo checkout.
"""
from __future__ import annotations

import os

from alembic import command
from alembic.config import Config

from .session import database_url

HERE = os.path.dirname(os.path.abspath(__file__))


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(HERE, "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url())
    return cfg


def upgrade(revision: str = "head") -> None:
    command.upgrade(alembic_config(), revision)


def current() -> None:
    command.current(alembic_config(), verbose=True)
