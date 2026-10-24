from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _script(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_nightly_entry_is_bounded_and_uses_project_runtime():
    text = _script("nightly-index.ps1")
    assert "--changed-only --resume" in text
    assert ".local\\integration-venv\\Scripts\\python.exe" in text
    assert ".local\\logs\\nightly-index" in text
    assert "SKIPPED_TIME_WINDOW" in text
    assert "SKIPPED_RUNNING" in text
    assert "02:00-04:00 local time" in text
    assert "AddDays(-30)" in text


def test_scheduler_scripts_encode_safe_registration_policy():
    install = _script("install-nightly-index.ps1")
    uninstall = _script("uninstall-nightly-index.ps1")
    assert "New-ScheduledTaskTrigger -Daily" in install
    assert "-RunOnlyIfIdle" in install
    assert "-IdleDuration (New-TimeSpan -Minutes 10)" in install
    assert "-IdleWaitTimeout (New-TimeSpan -Hours 1)" in install
    assert "-MultipleInstances IgnoreNew" in install
    assert "-Priority 7" in install
    assert "-LogonType Interactive" in install
    assert "-RunLevel Limited" in install
    assert "-DontStopOnIdleEnd" in install
    assert "-StartWhenAvailable" not in install
    assert "-WakeToRun" not in install
    assert "Export-ScheduledTask" in install
    assert "Unregister-ScheduledTask" in uninstall
    assert "not identified as Shutu-Atlas-managed" in uninstall
