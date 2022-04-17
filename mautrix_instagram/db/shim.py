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
