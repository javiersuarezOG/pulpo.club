"""RankerLeg Protocol."""
from __future__ import annotations
from typing import Protocol, runtime_checkable, TYPE_CHECKING
if TYPE_CHECKING:
    from pulpo.models import Listing


@runtime_checkable
class RankerLeg(Protocol):
    slug: str
    weight: float
    env_weight_key: str

    def score(self, listing: "Listing", comp_pool: list["Listing"]) -> tuple[float, str]:
        """Return (0..100 score, human-readable reason string)."""
        ...
