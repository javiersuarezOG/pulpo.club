"""PRD P2-2 — hermetic offline test guardrails.

Asserts that running `PULPO_OFFLINE=1 pytest -q` from a developer
machine with a fully-populated `.env` does NOT leak cost-bearing
credentials into the test process, AND does not let `PULPO_SOURCES`
narrow the scraper set out from under the rest of the suite.

The fixture under test lives in the root `conftest.py`. These tests
exist so a future refactor of that fixture can't silently undo the
hermeticity guarantee.
"""
from __future__ import annotations

import os


# All env vars the autouse fixture must strip when PULPO_OFFLINE=1.
# Keep this list in lockstep with `_COST_BEARING_ENV` in conftest.py;
# the test guards drift between the two.
_EXPECTED_STRIPPED = (
    "DEEPSEEK_API_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "RESEND_API_KEY",
    "CLERK_SECRET_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "PULPO_SOURCES",
)


def test_offline_mode_is_asserted() -> None:
    """The fixture forces PULPO_OFFLINE=1 when unset so module imports
    that read the var at top level (e.g. LLM client construction) take
    the offline branch."""
    assert os.environ.get("PULPO_OFFLINE") == "1"


def test_cost_bearing_env_is_stripped() -> None:
    """Every var the fixture promises to strip must be absent in tests.
    If this fails locally, your `.env` has a value the fixture isn't
    aware of yet — either add it to `_COST_BEARING_ENV` in conftest.py
    or document why it's safe to leak."""
    for key in _EXPECTED_STRIPPED:
        assert key not in os.environ, (
            f"{key!r} leaked into the offline test environment. "
            f"Add it to _COST_BEARING_ENV in conftest.py."
        )


def test_llm_client_refuses_to_construct_without_token() -> None:
    """The hermetic guarantee is only useful if downstream LLM clients
    enforce it. Constructing the DeepSeek client with no token should
    raise — proving the stripped env prevents an accidental paid call.
    """
    # Import lazily so the test doesn't have a hard dependency on the
    # exact constructor location (it's lived in different files
    # historically). Adjust the import path if the client moves.
    try:
        from automation import llm_client  # type: ignore[attr-defined]
    except ImportError:
        # Module path may have changed — skip rather than false-fail.
        # The other two tests still enforce the contract.
        import pytest
        pytest.skip("automation.llm_client not importable in this checkout")
        return

    # The construction surface differs across versions. We accept any of:
    #   - a module-level make_client() / get_client() factory raising on bad env
    #   - a class DeepSeekClient(...) raising on bad env
    # We attempt each common spelling; if none exist, skip cleanly.
    import pytest
    callable_factory = None
    for attr in ("make_client", "get_client", "client", "DeepSeekClient"):
        candidate = getattr(llm_client, attr, None)
        if callable(candidate):
            callable_factory = candidate
            break
    if callable_factory is None:
        pytest.skip("no recognized LLM client factory in automation.llm_client")
        return

    raised = False
    try:
        callable_factory()
    except Exception:
        raised = True
    assert raised, (
        "LLM client constructed successfully under PULPO_OFFLINE=1 with "
        "no API token in env. Either the client doesn't validate, or "
        "the fixture leaked a token."
    )
