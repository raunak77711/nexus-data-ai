"""Small English helpers for sentences the user reads.

WHY THIS MODULE EXISTS
----------------------
Every sentence this product shows is read as something a person wrote about
the reader's own file, and "5 thing(s) you should know" is the one construction
that gives away that nobody did. It costs the sentence its authority to save
four characters, and the sentences it appears in are the headlines.

So the rule is: no parenthesised plural reaches a screen. Where a count and a
noun appear together, they agree.

This is presentation only. Nothing here touches a value, a calculation or a
grounding check -- it decides whether a noun carries an "s".
"""

from __future__ import annotations

from typing import Optional

__all__ = ["plural", "count_of"]


def plural(count: int, singular: str, irregular: Optional[str] = None) -> str:
    """The plural form of `singular` for `count`, without the count itself.

    `irregular` is for the words English does not form by adding "s" --
    "category" -> "categories" being the one that started this.

    >>> plural(1, "thing")
    'thing'
    >>> plural(3, "category", "categories")
    'categories'
    """
    if count == 1:
        return singular
    return irregular if irregular is not None else singular + "s"


def count_of(count: int, singular: str, irregular: Optional[str] = None) -> str:
    """`3 things`, `1 thing`. The form wanted at almost every call site.

    >>> count_of(2, "measure")
    '2 measures'
    >>> count_of(1, "chart")
    '1 chart'
    """
    return f"{count:,} {plural(count, singular, irregular)}"
