"""Site-specific scrapers. Each module exposes `crawl(limit) -> list[dict]`."""
from . import goodlife, oceanside, kazu, century21, remax, bienesraices

REGISTRY = {
    "goodlife": goodlife,
    "oceanside": oceanside,
    "kazu": kazu,
    "century21": century21,
    "remax": remax,
    "bienesraices": bienesraices,
}
