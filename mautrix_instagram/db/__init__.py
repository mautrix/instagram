from mautrix.util.async_db import Database

from .message import Message
from .portal import Portal
from .puppet import Puppet
from .reaction import Reaction
from .upgrade import upgrade_table
from .user import User


def init(db: Database) -> None:
    for table in (User, Puppet, Portal, Message, Reaction):
        table.db = db


__all__ = ["upgrade_table", "User", "Puppet", "Portal", "Message", "Reaction", "init"]
