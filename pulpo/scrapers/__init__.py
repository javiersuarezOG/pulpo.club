"""Site-specific scrapers. Importing this module populates pulpo.agents.SOURCES."""
# Importing each module triggers its register() call
from . import goodlife, oceanside, kazu, century21, remax, bienesraices  # noqa: F401

from pulpo.agents import SOURCES

# Backward-compat alias — use pulpo.agents.SOURCES going forward
REGISTRY = SOURCES
