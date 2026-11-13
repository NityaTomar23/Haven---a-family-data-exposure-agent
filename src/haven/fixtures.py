"""Local synthetic listing fixtures.

Generic, identifier-free web searches cannot reveal whether a specific person
has a profile on a people-search site: confirming that would mean sending the
person's name to the site or to a search API, which Haven's privacy guarantee
forbids. The demo therefore matches the family against these LOCAL fixtures,
which stand in for listing pages a parent could retrieve themselves.

Every value is synthetic. Broker names are real companies (so the opt-out
procedure research is real); every listing URL uses the reserved ``.example``
TLD (RFC 2606) so none of them can resolve.

The fixtures cover four outcomes on purpose:

* verified  -- a name plus at least one other exact identifier match;
* candidate -- a name or alias only, with no conflicting location;
* rejected  -- a name match whose stated location contradicts the family;
* no match  -- a listing for someone else entirely.
"""

from __future__ import annotations

from pydantic import BaseModel

from haven.models import BrokerType


class SyntheticListing(BaseModel):
    broker: str
    broker_type: BrokerType
    url: str
    location: str | None  # the "City, ST" the listing states, if any
    text: str  # stands in for the listing page body; NEVER sent off-host


LISTINGS: list[SyntheticListing] = [
    SyntheticListing(
        broker="Spokeo",
        broker_type="people_search",
        url="https://spokeo.example/listing/avery-synthwell-ca",
        location="Sampleville, CA",
        text=(
            "Avery Synthwell, age 41. Current city: Sampleville, CA. "
            "Phone: (555) 555-0142. Possible relatives: Jordan Synthwell."
        ),
    ),
    SyntheticListing(
        broker="Whitepages",
        broker_type="people_search",
        url="https://whitepages.example/name/avery-synthwell/sampleville-ca",
        location="Sampleville, CA",
        text=(
            "Avery Synthwell lives at 100 Fictional Way, Sampleville, CA 00000. "
            "Landline and mobile numbers available with premium report."
        ),
    ),
    SyntheticListing(
        broker="Radaris",
        broker_type="data_broker",
        url="https://radaris.example/p/jordan/synthwell",
        location="Sampleville, CA",
        text=(
            "Jordan Synthwell, 43, Sampleville, CA. "
            "Email on file: jordan.synthwell@example.com. Employment history hidden."
        ),
    ),
    SyntheticListing(
        broker="FastPeopleSearch",
        broker_type="people_search",
        url="https://fastpeoplesearch.example/jordan-synthwell_id_00000",
        location="Sampleville, CA",
        text="Jordan Synthwell. Lives in Sampleville, CA. Age 40s.",
    ),
    SyntheticListing(
        broker="BeenVerified",
        broker_type="people_search",
        url="https://beenverified.example/people/jordy-synthwell",
        location=None,
        text="Jordy Synthwell — possible match. Unlock the full report to see details.",
    ),
    SyntheticListing(
        broker="TruePeopleSearch",
        broker_type="people_search",
        url="https://truepeoplesearch.example/find/avery-synthwell-riverton-or",
        location="Riverton, OR",
        text="Avery Synthwell, age 67, Riverton, OR. Phone: (555) 555-0177.",
    ),
    SyntheticListing(
        broker="Intelius",
        broker_type="data_broker",
        url="https://intelius.example/people/casey-otherfamily",
        location="Elsewhere, TX",
        text="Casey Otherfamily, age 29, Elsewhere, TX.",
    ),
]


def load_listings() -> list[SyntheticListing]:
    """Return a copy of the fixture listings."""
    return [listing.model_copy() for listing in LISTINGS]


def fixture_brokers() -> set[str]:
    return {listing.broker for listing in LISTINGS}

