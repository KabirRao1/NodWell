"""Translation hook. Every user-facing string goes through `_()` (CLAUDE.md §7).

For now it returns the text unchanged; adding a catalogue (Hindi first) later only
changes this module.
"""

from __future__ import annotations


def _(text: str) -> str:
    """Return `text` translated into the user's language."""
    return text
