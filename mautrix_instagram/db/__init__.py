from mautrix.util.async_db import Database

from .message import Message
from .portal import Portal
from .puppet import Puppet
from .reaction import Reaction
from .upgrade import upgrade_table
from .user import User

try:
    import asyncpg

    UniqueError = asyncpg.UniqueViolationError
    Record = asyncpg.Record
except ImportError:
    pass
try:
    import sqlite3

    UniqueError = sqlite3.IntegrityError
    Record = sqlite3.Row
except ImportError:
    pass

if UniqueError is None:
    raise ImportError("Must require either asyncpg or aiosqlite!")


def init(db: Database) -> None:
    for table in (User, Puppet, Portal, Message, Reaction):
        table.db = db


__all__ = ["upgrade_table", "User", "Puppet", "Portal", "Message", "Reaction", "init"]
