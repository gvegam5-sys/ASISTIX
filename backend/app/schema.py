"""Declarative metadata shared by the ORM and schema migrations."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
