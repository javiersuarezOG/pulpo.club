from __future__ import annotations

import pytest

from scripts import audit_last_run


def test_help_exits_without_writing_default_report(tmp_path, monkeypatch, capsys):
    out = tmp_path / "samples" / "last_run_audit.txt"
    monkeypatch.setattr(audit_last_run, "DEFAULT_OUT", out)

    with pytest.raises(SystemExit) as exc:
        audit_last_run.main(["--help"])

    assert exc.value.code == 0
    assert not out.exists()
    assert "--write" in capsys.readouterr().out
