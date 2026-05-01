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
    "pulpo/scrapers/": "tests/scrapers/",
    "pulpo/agents/": "tests/agents/",
    "pulpo/enrichers/": "tests/enrichers/",
    "pulpo/ranker_legs/": "tests/agents/",  # ranker legs tested under tests/agents/
}

SKIP_FILES = {"__init__.py", "base.py", "conftest.py"}


def check(added_files: list[str]) -> list[str]:
    """Return list of agent files that are missing a test counterpart."""
    missing = []
    for f in added_files:
        for agent_prefix, test_prefix in AGENT_TO_TEST.items():
            if not f.startswith(agent_prefix):
                continue
            stem = Path(f).name
            if stem in SKIP_FILES:
                break
            # Expected test file: e.g. pulpo/scrapers/foo.py -> tests/scrapers/test_foo.py
            expected = test_prefix + "test_" + stem
            if expected not in added_files and not Path(expected).exists():
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
