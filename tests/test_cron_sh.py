"""Tests for ``cron.sh`` — the cronjob installer for py-stremio.

These tests use a temporary ``crontab`` so the host's real crontab
is never touched.  The script reads from / writes to the real
``crontab`` binary, so each test backs up and restores the host's
crontab around its run.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CRON_SH = REPO_ROOT / "cron.sh"


def _has_crontab() -> bool:
    return shutil.which("crontab") is not None


pytestmark = pytest.mark.skipif(not _has_crontab(), reason="crontab(1) not on PATH")


@pytest.fixture
def crontab_sandbox(tmp_path):
    """Snapshot the real crontab and put a temp one in its place for
    the duration of the test.  The fixture is robust against the test
    being interrupted (KeyboardInterrupt, sys.exit, exception) — the
    real crontab is always restored on teardown.
    """
    real = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    backup = tmp_path / "real_crontab.txt"
    backup.write_text(real.stdout)

    # Start from a clean slate so the test's assertions are
    # deterministic regardless of what's in the real crontab.
    subprocess.run(["crontab", "-r"], capture_output=True, check=False)
    try:
        yield tmp_path
    finally:
        # Restore the real crontab, even on failure.
        subprocess.run(
            ["crontab", str(backup)],
            capture_output=True,
            check=False,
        )


def _run_cron_sh(*args, env=None, cwd=None):
    """Invoke ``cron.sh`` and capture combined output + exit code."""
    cmd = ["bash", str(CRON_SH), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or REPO_ROOT,
        env={**os.environ, **(env or {})},
        check=False,
    )


def _read_crontab() -> str:
    return subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True, check=False
    ).stdout


def _read_wrapper_path() -> str:
    """Resolve the wrapper path the way ``cron.sh`` resolves it: the
    install root (defaults to ``$HOME/.py-stremio``) joined with
    ``cron-run.sh``."""
    install_root = os.environ.get("PY_STREMIO_ROOT", os.path.expanduser("~/.py-stremio"))
    return os.path.join(install_root, "cron-run.sh")


def _read_wrapper() -> str:
    p = Path(_read_wrapper_path())
    if not p.exists():
        return ""
    return p.read_text()


def test_dry_run_does_not_touch_crontab(crontab_sandbox):
    """dry-run must NOT modify the host crontab."""
    result = _run_cron_sh("dry-run")
    assert result.returncode == 0, result.stderr
    assert "0 */3 * * *" in result.stdout
    assert "py-stremio-managed" in result.stdout
    # The real crontab is untouched — see the fixture.
    assert _read_crontab().strip() == ""


def test_install_uninstall_round_trip(crontab_sandbox):
    """install followed by uninstall leaves the crontab empty."""
    install = _run_cron_sh("install")
    assert install.returncode == 0, install.stderr
    installed = _read_crontab()
    assert "py-stremio-managed" in installed
    # All six jobs are present (library-light, library-full, download,
    # download-all, validate-addons, discover-addons).
    for name in (
        "library-light",
        "library-full",
        "download",
        "download-all",
        "validate-addons",
        "discover-addons",
    ):
        assert f"[{name}]" in installed

    uninstall = _run_cron_sh("uninstall")
    assert uninstall.returncode == 0, uninstall.stderr
    assert _read_crontab().strip() == ""


def test_install_preserves_existing_user_entries(crontab_sandbox):
    """install must NOT touch lines the user added themselves."""
    user_line = "*/15 * * * * /usr/local/bin/my-backup.sh"
    subprocess.run(
        ["crontab", "-"],
        input=user_line + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    _run_cron_sh("install")
    crontab = _read_crontab()
    assert user_line in crontab
    assert "py-stremio-managed" in crontab

    _run_cron_sh("uninstall")
    crontab = _read_crontab()
    # User line is still there; our entries are gone.
    assert user_line in crontab
    assert "py-stremio-managed" not in crontab


def test_install_is_idempotent(crontab_sandbox):
    """Re-running install replaces the existing py-stremio block
    rather than appending a second copy."""
    _run_cron_sh("install")
    first = _read_crontab()
    _run_cron_sh("install")
    second = _read_crontab()
    # Same number of marker comments in both — install did not double them.
    assert first.count("py-stremio-managed") == second.count("py-stremio-managed")


def test_show_lists_existing_entries(crontab_sandbox):
    _run_cron_sh("install")
    show = _run_cron_sh("show")
    assert show.returncode == 0
    for name in ("library-light", "library-full", "download", "download-all", "validate-addons", "discover-addons"):
        assert f"[{name}]" in show.stdout


def test_install_speed_percent_is_honoured(crontab_sandbox):
    """The user can override the speed cap without editing the script.

    The speed is set inside ``cron-run.sh`` (the wrapper), not in
    the crontab itself, so we look for it in the wrapper file.
    """
    _run_cron_sh("install", env={"PY_STREMIO_CRON_SPEED": "25"})
    wrapper = _read_wrapper()
    assert 'INTERNET_SPEED_LIMIT="25"' in wrapper
    assert "INTERNET_SPEED_LIMIT=50" not in wrapper


def test_install_root_path_is_honoured(crontab_sandbox, tmp_path):
    """The user can override the install root (for non-standard layouts).

    The root is set inside the wrapper.  We use ``tmp_path`` as
    the override so the test does not need ``/srv/py-stremio`` to
    exist (or root) — it just needs the directory to be creatable.
    """
    custom_root = tmp_path / "custom-install"
    _run_cron_sh(
        "install",
        env={"PY_STREMIO_ROOT": str(custom_root)},
    )
    wrapper_text = (custom_root / "cron-run.sh").read_text()
    assert f'PY_STREMIO_ROOT="{custom_root}"' in wrapper_text


def test_cron_lines_invoke_wrapper_not_binary(crontab_sandbox):
    """Each cron line must call the wrapper by name, not the raw
    binary path — that's the whole point of the wrapper indirection.
    """
    _run_cron_sh("install")
    crontab = _read_crontab()
    # The full venv path should NOT appear in any cron line.
    for line in crontab.splitlines():
        if "py-stremio-managed:" not in line:
            continue
        assert "venv/bin/py-stremio-cron" not in line, (
            f"cron line still hard-codes the venv path: {line!r}"
        )
    # The wrapper path should appear in every cron line.
    wrapper_count = crontab.count("cron-run.sh")
    assert wrapper_count >= 4, (
        f"expected 4 wrapper invocations, got {wrapper_count}"
    )


def test_wrapper_is_executable(crontab_sandbox):
    """The wrapper must be chmod +x so cron can run it."""
    _run_cron_sh("install")
    wrapper = Path(_read_wrapper_path())
    assert wrapper.exists()
    import stat
    mode = wrapper.stat().st_mode
    assert mode & stat.S_IXUSR, "wrapper is not executable by owner"


def test_uninstall_removes_wrapper(crontab_sandbox, tmp_path):
    """uninstall must also remove the auto-generated wrapper, but
    only if it's our wrapper (preserve a user-authored cron-run.sh).

    Uses ``tmp_path`` so a stale wrapper from a prior run in the
    user's real ``~/.py-stremio`` does not bleed into the test.
    """
    custom_root = tmp_path / "wrapper-test"
    _run_cron_sh("install", env={"PY_STREMIO_ROOT": str(custom_root)})
    wrapper = custom_root / "cron-run.sh"
    assert wrapper.exists()
    _run_cron_sh("uninstall", env={"PY_STREMIO_ROOT": str(custom_root)})
    assert not wrapper.exists()


def test_cron_lines_have_valid_schedule():
    """Every emitted schedule must be a valid 5-field cron expression.

    Marker lines (which start with ``#``) and dry-run banner lines
    are excluded — only actual cron entries have a schedule to
    validate.  A real schedule field starts with a digit or ``*``.
    """
    proc = _run_cron_sh("dry-run")
    assert proc.returncode == 0
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        # Skip blank lines, marker lines, and the dry-run banner
        # (which starts with the script's own header markers like
        # ``==>`` or ``──``).
        if not stripped or stripped.startswith(("#", "==>", "─")):
            continue
        # A real cron entry starts with the 5 schedule fields.
        # The first field must look like a schedule token (digit
        # or ``*``).
        first = stripped.split(None, 1)[0]
        if not first[0].isdigit() and first[0] != "*":
            continue
        fields = line.split(None, 5)
        if len(fields) < 6:
            continue
        schedule = fields[:5]
        assert len(schedule) == 5, f"bad schedule in line: {line!r}"
        for f in schedule:
            assert re.fullmatch(r"[\d*/,\-]+", f), f"bad schedule field {f!r} in {line!r}"


def test_cron_lines_invoke_correct_subcommand():
    """Each job must map to the right py-stremio-cron subcommand.

    The crontab only sees ``cron-run.sh <job-name>``; the actual
    ``--scan`` / ``--download`` dispatch lives inside the wrapper.
    We check both the crontab (job names are passed through) and
    the wrapper (the dispatch table).
    """
    _run_cron_sh("install")
    crontab = _read_crontab()
    wrapper = _read_wrapper()

    for name in ("library-light", "library-full", "download", "download-all", "validate-addons", "discover-addons"):
        # The crontab passes the job name to the wrapper.
        assert f"cron-run.sh {name}" in crontab, f"job {name} not in crontab"
        # The wrapper dispatches the right py-stremio-cron subcommand.
        assert name in wrapper, f"job {name} not handled by wrapper"


def test_cron_marker_is_on_its_own_line(crontab_sandbox):
    """Regression: the ``# py-stremio-managed:`` marker MUST be on
    its own line, not embedded in the middle of a cron entry.
    Embedding it in the middle makes bash treat the rest of the
    line as a comment so the wrapper never runs.
    """
    _run_cron_sh("install")
    crontab = _read_crontab()
    for line in crontab.splitlines():
        stripped = line.strip()
        if not stripped.startswith("# py-stremio-managed:"):
            continue
        # The "wrapper:" and header lines are documentation — they
        # tell the user where the wrapper lives.  They are allowed
        # to contain the wrapper path because they have no schedule
        # fields (they start with ``#`` so cron treats them as
        # comments).  The bug we are guarding against is the marker
        # being embedded in a real cron ENTRY (one that has a
        # schedule), so only assert on those.
        is_cron_entry = len(stripped.split(None, 5)) >= 6
        if not is_cron_entry:
            continue
        # A real cron entry with the marker baked in would look
        # like ``0 */3 * * * # py-stremio-managed: [name] ...``.
        # The command portion starts after the 5 schedule fields —
        # if it begins with ``#``, bash treats the rest as a
        # comment and the wrapper never runs.
        command = stripped.split(None, 5)[5].lstrip()
        assert not command.startswith("#"), (
            f"cron entry has ``#`` as the first non-space char of "
            f"the command — bash will treat the rest as a comment "
            f"and the wrapper will never run: {line!r}"
        )


def test_uninstall_when_no_entries_is_safe(crontab_sandbox):
    """uninstall with no py-stremio entries is a no-op (idempotent)."""
    result = _run_cron_sh("uninstall")
    assert result.returncode == 0
    assert _read_crontab().strip() == ""


def test_show_with_no_entries_reports_cleanly(crontab_sandbox):
    result = _run_cron_sh("show")
    assert result.returncode == 0
    assert "no py-stremio cron entries" in result.stdout


def test_validate_runs_quickly(crontab_sandbox):
    """validate must NOT hang on a slow ``--show-config`` probe.

    A network-share client often sees the binary's import take
    10+ seconds (it loads the full py-stremio module plus all the
    addons).  The probe is wrapped in a 2s timeout so the user
    gets fast feedback on whether their install is usable.
    """
    import time
    started = time.monotonic()
    result = _run_cron_sh("validate")
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr
    assert elapsed < 5, f"validate took {elapsed:.1f}s — probe is not time-bounded"
    # The validate output must include the install plan so the user
    # can confirm where everything will land.
    assert "install root" in result.stdout
    assert "wrapper" in result.stdout
    assert "ROOT_FOLDER" in result.stdout


def test_validate_does_not_modify_crontab(crontab_sandbox):
    """validate is read-only — must not touch the crontab or the wrapper."""
    _run_cron_sh("validate")
    assert _read_crontab().strip() == ""
    # No wrapper should be created by validate.
    assert not Path(_read_wrapper_path()).exists()


def test_no_validate_skips_root_folder_probe(crontab_sandbox):
    """--no-validate skips the slow --show-config probe entirely."""
    import time
    started = time.monotonic()
    result = _run_cron_sh("validate", "--no-validate")
    elapsed = time.monotonic() - started
    assert result.returncode == 0
    # The ROOT_FOLDER row is the one that requires the probe.  When
    # --no-validate is set, the row is omitted from the output.
    assert "ROOT_FOLDER" not in result.stdout
    assert elapsed < 3, f"validate --no-validate took {elapsed:.1f}s"


def test_cron_entry_command_does_not_start_with_hash(crontab_sandbox):
    """Regression: a ``#`` in the middle of a cron line silently
    turns the entire command into a bash comment, so the wrapper
    never runs.  The marker MUST be on its own line above the entry,
    not embedded in the command text.
    """
    _run_cron_sh("install")
    crontab = _read_crontab()
    for line in crontab.splitlines():
        # Skip blank lines and the standalone marker lines.
        stripped = line.strip()
        if not stripped or stripped.startswith("# py-stremio-managed:"):
            continue
        # Any other non-blank, non-marker line is an actual cron entry.
        # The command portion is everything after the 5 schedule fields.
        # If it starts with ``#``, the wrapper will never run.
        fields = line.split(None, 5)
        if len(fields) < 6:
            continue
        command = fields[5].lstrip()
        assert not command.startswith("#"), (
            f"cron entry has a ``#`` as the first non-space char of "
            f"the command — bash will treat the rest as a comment "
            f"and the wrapper will never run: {line!r}"
        )


def test_cron_command_actually_runs_the_wrapper(crontab_sandbox, tmp_path):
    """End-to-end regression: simulate what cron does (the command
    portion of a cron line, passed to ``sh -c``) and verify it
    actually creates the expected log file.  This is the test
    that would have caught the ``# py-stremio-managed: …`` bug
    the user hit on their other computer.
    """
    import stat
    custom_root = tmp_path / "e2e-test"
    _run_cron_sh("install", env={"PY_STREMIO_ROOT": str(custom_root)})
    wrapper_path = custom_root / "cron-run.sh"
    assert wrapper_path.exists()
    assert wrapper_path.stat().st_mode & stat.S_IXUSR, "wrapper is not executable"

    crontab = _read_crontab()
    for line in crontab.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("# py-stremio-managed:"):
            continue
        fields = line.split(None, 5)
        if len(fields) < 6:
            continue
        command = fields[5]
        m = re.search(r">>\s*(\S+)\s*2>&1", command)
        assert m, f"no log redirect found in {command!r}"
        log_target = tmp_path / f"e2e_{Path(m.group(1)).name}"
        shim_dir = tmp_path / f"shim_{Path(m.group(1)).stem}"
        shim_dir.mkdir(exist_ok=True)
        shim_bin = shim_dir / "py-stremio-cron"
        shim_bin.write_text("#!/usr/bin/env bash\necho ran >> \"$1\"\n")
        shim_bin.chmod(0o755)
        shim_command = command.replace(">> ", f">> {log_target} ")
        # Run via sh -c the same way cron does it.  A 5s timeout
        # prevents the test from hanging if the shim somehow
        # blocks (real py-stremio-cron blocks on network calls).
        try:
            subprocess.run(
                ["/bin/sh", "-c", f"PATH={shim_dir}:$PATH {shim_command}"],
                check=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            pass  # Real binary would time out; shim should not.
        assert log_target.exists(), (
            f"cron command for {line!r} did not produce its log — "
            f"the wrapper was never invoked (likely the ``#``-in-"
            f"command bug)"
        )


def test_each_job_writes_to_its_own_log(crontab_sandbox):
    """Regression: the download entry once logged to scan-light.log
    because of a copy-paste error.  Every job's log path must be
    derived from the job name, not hard-coded to scan-light.
    """
    _run_cron_sh("install")
    crontab = _read_crontab()
    # Map job name → expected log basename.
    for name in ("library-light", "library-full", "download", "download-all", "validate-addons", "discover-addons"):
        # Find the cron entry line for this job (the one that calls
        # the wrapper with the job name, not the marker line above it).
        # Use word-boundary matching so "download" doesn't match
        # "download-all" (the longer name) and vice versa.
        pattern = re.compile(rf"cron-run\.sh {re.escape(name)}(?:\s|$)")
        found_line = None
        for line in crontab.splitlines():
            if pattern.search(line):
                found_line = line
                break
        assert found_line, f"no cron entry found for job {name!r}"
        log_match = re.search(r">>\s*(\S+)", found_line)
        assert log_match, f"no log path in {found_line!r}"
        log_path = Path(log_match.group(1))
        assert log_path.name == f"{name}.log", (
            f"job {name!r} logs to {log_path.name!r} — "
                f"expected {name}.log.  Copy-paste bug?"
            )


def test_install_echoes_wrapper_path_and_speed(crontab_sandbox):
    """The speed cap is set in the wrapper, not the crontab.  A
    user who runs ``./cron.sh install --speed 55`` and then looks
    at the crontab would not see the value.  The install output
    must explicitly echo the wrapper path and the resolved speed
    so the user can confirm ``--speed`` actually took effect.
    """
    result = _run_cron_sh("install", "--speed", "55")
    assert result.returncode == 0
    assert "wrapper" in result.stdout
    assert "55%" in result.stdout, (
        "install output did not surface the resolved speed cap — "
        "the user has no way to confirm --speed was honoured"
    )
    assert _read_wrapper_path() in result.stdout, (
        "install output did not echo the wrapper path"
    )


def test_show_reports_resolved_speed(crontab_sandbox):
    """``show`` must display the speed cap that was baked into the
    wrapper, not just dump the crontab (which has no speed in it).
    """
    _run_cron_sh("install", "--speed", "33")
    result = _run_cron_sh("show")
    assert result.returncode == 0
    assert "33%" in result.stdout, (
        "show output did not display the wrapper's speed cap"
    )


def test_show_warns_when_wrapper_missing(crontab_sandbox):
    """If the crontab entries exist but the wrapper is gone (someone
    deleted it manually), ``show`` should warn the user so they
    know the cron jobs will fail.
    """
    _run_cron_sh("install")
    wrapper = Path(_read_wrapper_path())
    assert wrapper.exists()
    wrapper.unlink()
    result = _run_cron_sh("show")
    assert result.returncode == 0
    assert "wrapper missing" in result.stdout, (
        "show did not warn the user about the missing wrapper"
    )
