"""Site-specific scrapers. Each module exposes `crawl(limit) -> list[dict]`."""
from . import goodlife, oceanside, kazu

REGISTRY = {
    "goodlife": goodlife,
    "oceanside": oceanside,
    "kazu": kazu,
}
