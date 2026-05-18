#!/usr/bin/env python3
"""
Fail if a PR adds a new source/agent/enricher file without a matching test.

Usage: python .github/scripts/check_tests_added.py <diff_namelist_file>
  where diff_namelist_file contains one added filename per line (from git diff).

Exit 0 = OK, Exit 1 = missing tests found.
"""
import sys
from pathlib import Path

# Map: source dir prefix -> required test dir prefix
AGENT_TO_TEST = {
    "pulpo/scrapers/":    "tests/scrapers/",
    "pulpo/agents/":      "tests/agents/",
    "pulpo/enrichers/":   "tests/enrichers/",
    "pulpo/ranker_legs/": "tests/agents/",
}

# Files that never need a dedicated test (boilerplate, protocols, shared infra)
SKIP_FILES = {
    "__init__.py",
    "base.py",
    "conftest.py",
    # Protocol definitions — pure type hints, no runnable logic
    "source.py",
    "ranker_leg.py",
    # Shared HTTP infrastructure — tested indirectly through every scraper test
    "html_crawler.py",
}

# Collective test files: a single test file covers all modules in a directory.
# If this file exists (on disk or in the PR diff) the whole dir is considered covered.
COLLECTIVE_TESTS = {
    "pulpo/ranker_legs/": "tests/agents/test_ranker_legs.py",
}


def check(added_files: list[str]) -> list[str]:
    """Return list of agent files that are missing a test counterpart."""
    added_set = set(added_files)
    missing = []

    for f in added_files:
        for agent_prefix, test_prefix in AGENT_TO_TEST.items():
            if not f.startswith(agent_prefix):
                continue

            stem = Path(f).name
            if stem in SKIP_FILES:
                break
            # Data / config files (e.g. photo_config.json) are covered by
            # the schema-validation tests that live alongside the helper
            # they configure — they aren't agents themselves.
            if not stem.endswith(".py"):
                break

            # Check for a collective test that covers this whole directory
            collective = COLLECTIVE_TESTS.get(agent_prefix)
            if collective and (collective in added_set or Path(collective).exists()):
                break  # covered by the collective test

            # Expected individual test file
            expected = test_prefix + "test_" + stem
            if expected not in added_set and not Path(expected).exists():
                missing.append(f"  {f}  →  needs  {expected}")
            break

    return missing


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: check_tests_added.py <diff_file>", file=sys.stderr)
        return 2

    added = Path(sys.argv[1]).read_text().splitlines()
    added = [f.strip() for f in added if f.strip()]

    missing = check(added)
    if missing:
        print("❌  Missing test files for newly added agents:")
        for m in missing:
            print(m)
        print("\nAdd a test file or label the PR 'no-test-required' to skip.")
        return 1

    print(f"✅  {len(added)} added files checked — all agents have tests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
