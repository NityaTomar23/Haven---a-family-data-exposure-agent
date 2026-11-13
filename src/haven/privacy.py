"""Deterministic outbound payload gate.

Every request body Haven sends to a provider -- Tavily Search, Tavily Extract,
Token Factory chat completions -- passes through :func:`check` *before* the
SDK client is even constructed. If the payload contains any protected term,
the call raises :class:`PayloadBlocked` and nothing is sent. The gate fails
closed: when no family has been registered it protects the built-in demo
family and fixtures, so there is no "unarmed" state.

Protected terms:

* every family identifier value, regardless of its sensitivity label;
* each member's full name and the family surname on its own;
* phone numbers in any punctuation (digits are compared, not strings);
* email addresses and their local parts;
* the street address and the city/state pair;
* every local listing URL and every sentence of raw listing text.

First names on their own are deliberately *not* protected: "Jordan" appears
in ordinary web pages, and a gate that blocks legitimate opt-out pages would
be switched off in practice. A first name without the surname is not an
identifier.

This gate is application code. It constrains Haven's own request paths; it is
not a substitute for the sandbox, which constrains the process as a whole.
Messages never include the matched value, so a blocked payload cannot leak
through logs or exception text.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from haven.models import Family

_MIN_SENTENCE = 24  # shorter listing fragments are too generic to protect


@dataclass(frozen=True)
class _Term:
    category: str
    pattern: re.Pattern[str]


class PayloadBlocked(RuntimeError):
    """Raised when an outbound payload contains a protected term."""

    def __init__(self, channel: str, category: str) -> None:
        super().__init__(
            f"outbound payload to {channel} blocked: it contains a protected "
            f"{category}. Nothing was sent."
        )
        self.channel = channel
        self.category = category


_lock = threading.Lock()
_terms: list[_Term] | None = None
_blocked: list[tuple[str, str]] = []  # (channel, category) -- never the value


def _literal(value: str) -> re.Pattern[str]:
    return re.compile(re.escape(value.strip()), re.IGNORECASE)


def _word(value: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(value.strip())}\b", re.IGNORECASE)


def _phone(value: str) -> re.Pattern[str] | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 7:
        return None
    # Match the last seven digits with any separators between groups, so
    # "555-0142", "5550142" and "555 . 0142" are all caught.
    exchange, line = digits[-7:-4], digits[-4:]
    return re.compile(rf"{exchange}\D{{0,3}}{line}")


def build_terms(family: Family, listings: list | None = None) -> list[_Term]:
    """Compile the protected-term list for a family and its local listings."""
    terms: list[_Term] = []
    seen: set[str] = set()

    def add(category: str, pattern: re.Pattern[str] | None) -> None:
        if pattern is None or pattern.pattern in seen:
            return
        seen.add(pattern.pattern)
        terms.append(_Term(category, pattern))

    for member in family.members:
        add("name", _literal(f"{member.first_name} {member.last_name}"))
        add("surname", _word(member.last_name))
        for ident in member.identifiers:
            if ident.kind == "phone":
                add("phone", _phone(ident.value))
            elif ident.kind == "email":
                add("email", _literal(ident.value))
                add("email", _word(ident.value.split("@", 1)[0]))
            else:
                add(ident.kind, _literal(ident.value))

    add("address", _literal(family.address))
    add("city_state", _literal(f"{family.city}, {family.state}"))

    for listing in listings or []:
        add("listing_url", _literal(listing.url))
        for sentence in re.split(r"(?<=[.!?])\s+", listing.text):
            if len(sentence.strip()) >= _MIN_SENTENCE:
                add("listing_text", _literal(sentence))

    return terms


def register(family: Family, listings: list | None = None) -> None:
    """Arm the gate for *family* (replacing any previous registration)."""
    global _terms
    compiled = build_terms(family, listings)
    with _lock:
        _terms = compiled


def _active_terms() -> list[_Term]:
    global _terms
    with _lock:
        if _terms is not None:
            return _terms
    # Fail closed: never run unarmed. Import lazily to avoid a cycle.
    from haven.fixtures import load_listings
    from haven.seed import generate_family

    register(generate_family(), load_listings())
    with _lock:
        assert _terms is not None
        return _terms


def find_violation(payload: str) -> str | None:
    """Return the category of the first protected term in *payload*, if any."""
    for term in _active_terms():
        if term.pattern.search(payload):
            return term.category
    return None


def check(channel: str, *payloads: str) -> None:
    """Raise :class:`PayloadBlocked` if any payload contains a protected term."""
    for payload in payloads:
        if not payload:
            continue
        category = find_violation(payload)
        if category is not None:
            with _lock:
                _blocked.append((channel, category))
            raise PayloadBlocked(channel, category)


def blocked_events() -> list[tuple[str, str]]:
    """(channel, category) for every blocked payload -- no values."""
    with _lock:
        return list(_blocked)


def reset() -> None:
    """Clear the registration and the blocked-event log (tests only)."""
    global _terms
    with _lock:
        _terms = None
        _blocked.clear()

