"""Sortable identifiers, ``<prefix>_<ulid>``.

Database autoincrement ids never leave the store. Every id a client sees comes
from here.
"""

from ulid import ULID

PREFIXES = {
    "audit": "aud",
    "project": "prj",
    "snapshot": "snap",
    "document": "doc",
    "segment": "seg",
    "recipe": "rcp",
    "recipe_version": "rcv",
    "run": "run",
    "batch": "bat",
    "query": "qry",
    "judgment": "jdg",
    "generation": "gen",
    "conversation": "cnv",
    "dataset": "ds",
    "sample": "smp",
    "revision": "rev",
    "review": "rvw",
    "release": "rel",
    "export": "exp",
    "invocation": "inv",
    "job": "job",
}


def new_id(kind: str) -> str:
    """A new id for ``kind``. Unknown kinds are a programming error."""
    prefix = PREFIXES[kind]
    return f"{prefix}_{ULID()}"
