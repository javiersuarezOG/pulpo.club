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

    import os
    added = Path(sys.argv[1]).read_text().splitlines()
    added = [f.strip() for f in added if f.strip()]

    missing = check(added)
    bypass_active = os.environ.get("PULPO_TESTS_BYPASS_ACTIVE") == "1"

    if not missing:
        print(f"✅  {len(added)} added files checked — all agents have tests.")
        if bypass_active:
            # Operator labelled the PR for bypass but the script would
            # have passed anyway — flag the dead label so it can be
            # removed (it's misleading on a clean PR).
            print(
                "::notice::PR has the 'no-test-required' label but all "
                "added agents already have matching tests — the bypass "
                "is unnecessary and can be removed.",
            )
        return 0

    print("❌  Missing test files for newly added agents:")
    for m in missing:
        print(m)
    if bypass_active:
        # Honor the bypass but make it LOUD. GitHub Actions renders
        # ::warning:: as a yellow banner on the check run and as a
        # PR annotation; the reviewer sees exactly which files were
        # waved through. Audit-fix from PR-7 of the reliability plan —
        # the legacy `if:` gate skipped the whole job and left no trail.
        print(
            "::warning::TEST COVERAGE BYPASS ACTIVE — the "
            "'no-test-required' label is letting this PR ship without "
            f"the {len(missing)} test file(s) listed above. Confirm "
            "this is genuinely a docs / data / config PR before merging.",
        )
        # Exit 0 so the bypass still unblocks the merge (matches the
        # legacy behavior the operator expects), but the warning above
        # is permanent in both the run log + the PR's checks tab.
        return 0

    print("\nAdd a test file or label the PR 'no-test-required' to skip.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
