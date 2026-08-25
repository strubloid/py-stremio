"""Tests for the ffmpeg-backed HLS downloader and its dispatcher integration."""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.download import hls_download, hls_ffmpeg_download
from py_stremio.components.download.hls_ffmpeg_download import (
    HlsFfmpegDownloader,
    HlsFfmpegError,
    HlsFfmpegStallError,
    _bandwidth_quota_bps,
    find_ffmpeg,
    is_m3u8_url,
    reset_ffmpeg_probe,
    warn_missing_ffmpeg,
)
from py_stremio.components.download.stream_download import (
    _download_hls_to_file,
    _is_hls_url,
    download_stream_to_file,
)


# ── ffmpeg discovery ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _disable_min_video_size(monkeypatch):
    """Zero the minimum-completed-size check so test files (well under
    100 MB) are not rejected by ``_validate_and_finalize``."""
    from py_stremio.components.configs import app_settings

    monkeypatch.setattr(
        app_settings.settings,
        "MIN_COMPLETED_VIDEO_SIZE_MB",
        0,
        raising=False,
    )
    reset_ffmpeg_probe()
    yield
    reset_ffmpeg_probe()


def test_find_ffmpeg_returns_path_when_binary_on_path():
    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value="/usr/bin/ffmpeg",
    ):
        reset_ffmpeg_probe()
        assert find_ffmpeg() == "/usr/bin/ffmpeg"


def test_find_ffmpeg_caches_result_across_calls():
    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value="/usr/bin/ffmpeg",
    ) as which_mock:
        reset_ffmpeg_probe()
        find_ffmpeg()
        find_ffmpeg()
        find_ffmpeg()
    assert which_mock.call_count == 1


def test_find_ffmpeg_returns_none_when_missing():
    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value=None,
    ):
        reset_ffmpeg_probe()
        assert find_ffmpeg() is None


def test_find_ffmpeg_caches_none_result():
    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value=None,
    ) as which_mock:
        reset_ffmpeg_probe()
        find_ffmpeg()
        find_ffmpeg()
    assert which_mock.call_count == 1


def test_reset_ffmpeg_probe_clears_cache():
    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value="/usr/bin/ffmpeg",
    ) as which_mock:
        reset_ffmpeg_probe()
        find_ffmpeg()
        reset_ffmpeg_probe()
        find_ffmpeg()
    assert which_mock.call_count == 2


# ── is_m3u8_url helper ────────────────────────────────────────────────


def test_is_m3u8_url_accepts_m3u8_and_m3u():
    assert is_m3u8_url("https://hdhub.test/x/1080p.m3u8")
    assert is_m3u8_url("https://hdhub.test/x/master.m3u")
    assert is_m3u8_url("http://x.test/a.m3u8?token=abc")


def test_is_m3u8_url_rejects_other_extensions():
    assert not is_m3u8_url("https://x.test/a.mp4")
    assert not is_m3u8_url("https://x.test/a.mkv")
    assert not is_m3u8_url("https://x.test/a.ts")


def test_is_m3u8_url_handles_empty_and_invalid():
    assert not is_m3u8_url(None)
    assert not is_m3u8_url("")
    assert not is_m3u8_url("not a url")


# ── _bandwidth_quota_bps ──────────────────────────────────────────────


def test_bandwidth_quota_returns_zero_when_no_limiter():
    assert _bandwidth_quota_bps(None) == 0


def test_bandwidth_quota_uses_fair_share_bps():
    limiter = SimpleNamespace(get_fair_share_bps=lambda: 1_250_000)
    # 1_250_000 B/s * 8 = 10_000_000 bps
    assert _bandwidth_quota_bps(limiter) == 10_000_000


def test_bandwidth_quota_falls_back_to_bytes_per_second():
    limiter = SimpleNamespace(bytes_per_second=500_000)
    assert _bandwidth_quota_bps(limiter) == 4_000_000


def test_bandwidth_quota_handles_limiter_that_raises():
    class Broken:
        def get_fair_share_bps(self):
            raise RuntimeError("nope")

    assert _bandwidth_quota_bps(Broken()) == 0


def test_bandwidth_quota_handles_unlimited_limiter():
    limiter = SimpleNamespace(get_fair_share_bps=lambda: 0)
    assert _bandwidth_quota_bps(limiter) == 0


# ── HlsFfmpegDownloader._build_command ────────────────────────────────


def test_build_command_omits_maxrate_when_no_limiter():
    downloader = HlsFfmpegDownloader()
    cmd = downloader._build_command("/usr/bin/ffmpeg", "https://x.test/m.m3u8", Path("/tmp/o.mkv.part"))
    assert cmd[0] == "/usr/bin/ffmpeg"
    assert "-nostdin" in cmd
    assert "-hide_banner" in cmd
    assert "-loglevel" in cmd
    assert "error" in cmd
    assert "-maxrate" not in cmd
    assert "-bufsize" not in cmd
    assert "-progress" in cmd
    assert "pipe:1" in cmd
    assert "-c" in cmd
    assert "copy" in cmd
    # The partial filename has no recognized extension, so the
    # muxer is pinned explicitly to matroska.
    assert "-f" in cmd
    assert cmd[cmd.index("-f") + 1] == "matroska"
    assert cmd[-1].endswith(".part")
    url_index = cmd.index("-i") + 1
    assert cmd[url_index] == "https://x.test/m.m3u8"


def test_build_command_includes_maxrate_when_limiter_active():
    limiter = SimpleNamespace(get_fair_share_bps=lambda: 1_250_000)
    downloader = HlsFfmpegDownloader(bandwidth_limiter=limiter)
    cmd = downloader._build_command("/usr/bin/ffmpeg", "https://x.test/m.m3u8", Path("/tmp/o.mkv.part"))
    maxrate_index = cmd.index("-maxrate")
    bufsize_index = cmd.index("-bufsize")
    assert cmd[maxrate_index + 1] == str(10_000_000)  # 1.25 MB/s = 10 Mb/s
    assert cmd[bufsize_index + 1] == str(20_000_000)


# ── HlsFfmpegDownloader.download ──────────────────────────────────────


def _fake_popen_success(*, output_bytes: bytes, progress_lines: list[str] | None = None):
    """Build a ``Popen`` mock that emits *progress_lines* then exits 0.

    Writes *output_bytes* to the ``.part`` file path ffmpeg was given
    (taken from the cmdline) so the post-run validation passes.
    """
    lines = progress_lines if progress_lines is not None else [
        "frame=10\n",
        "total_size=1024\n",
        "out_time_us=1000000\n",
        "progress=continue\n",
        "total_size=2048\n",
        "out_time_us=2000000\n",
        "progress=end\n",
    ]

    def _factory(cmd, **_kwargs):
        # Extract the output file path (last argv element).
        output_path = Path(cmd[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(output_bytes)

        stdout = io.StringIO("".join(lines))
        stderr = io.StringIO("")
        proc = MagicMock()
        proc.stdout = stdout
        proc.stderr = stderr
        # ``readline`` on a StringIO returns "" once exhausted.
        # ``poll()`` returns the returncode so the loop terminates.
        proc.poll.side_effect = [None] * len(lines) + [0]
        proc.wait.return_value = 0
        return proc

    return _factory


def test_download_writes_file_via_ffmpeg(tmp_path):
    target = tmp_path / "show.mkv"
    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value="/usr/bin/ffmpeg",
    ), patch(
        "py_stremio.components.download.hls_ffmpeg_download.subprocess.Popen",
        side_effect=_fake_popen_success(output_bytes=b"\x00" * 4096),
    ):
        downloader = HlsFfmpegDownloader()
        size = downloader.download(
            "https://hdhub.test/resolve/.../1080p.m3u8",
            str(target),
        )
    assert size == 4096
    assert target.exists()
    assert target.stat().st_size == 4096
    assert not (tmp_path / "show.mkv.part").exists()


def test_download_emits_progress_through_callback(tmp_path):
    target = tmp_path / "show.mkv"
    progress = []
    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value="/usr/bin/ffmpeg",
    ), patch(
        "py_stremio.components.download.hls_ffmpeg_download.subprocess.Popen",
        side_effect=_fake_popen_success(output_bytes=b"\x00" * 1024),
    ):
        downloader = HlsFfmpegDownloader(
            progress_callback=lambda done, total: progress.append((done, total)),
        )
        downloader.download("https://x.test/m.m3u8", str(target))
    # The final callback uses (final_size, final_size); intermediate
    # emissions are rate-limited to 1/sec which the fake triggers
    # immediately because time.monotonic is monotonic in tests.
    assert progress
    assert progress[-1] == (1024, 1024)


def test_download_raises_when_ffmpeg_missing(tmp_path):
    target = tmp_path / "show.mkv"
    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value=None,
    ):
        downloader = HlsFfmpegDownloader()
        with pytest.raises(HlsFfmpegError, match="ffmpeg binary not found"):
            downloader.download("https://x.test/m.m3u8", str(target))
    assert not target.exists()


def test_download_raises_when_ffmpeg_nonzero_returncode(tmp_path):
    target = tmp_path / "show.mkv"
    factory = _fake_popen_success(output_bytes=b"")
    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value="/usr/bin/ffmpeg",
    ), patch(
        "py_stremio.components.download.hls_ffmpeg_download.subprocess.Popen",
        side_effect=factory,
    ) as popen_mock:
        # Override the proc to report a non-zero exit.
        original = popen_mock.side_effect

        def _wrapper(cmd, **kw):
            proc = original(cmd, **kw)
            proc.poll.side_effect = [None, 1]
            proc.wait.return_value = 1
            proc.stderr = io.StringIO("HTTP error 403")
            return proc

        popen_mock.side_effect = _wrapper
        downloader = HlsFfmpegDownloader()
        with pytest.raises(HlsFfmpegError, match="exited with code 1"):
            downloader.download("https://x.test/m.m3u8", str(target))
    assert not target.exists()
    assert not (tmp_path / "show.mkv.part").exists()


def test_download_raises_stall_when_no_progress(tmp_path, monkeypatch):
    """If ffmpeg never reports a total_size and the process hangs, the
    downloader should give up after ``stall_timeout`` seconds."""
    target = tmp_path / "show.mkv"

    def _stuck_factory(cmd, **_kw):
        proc = MagicMock()
        proc.stdout = io.StringIO("")  # no progress lines
        proc.stderr = io.StringIO("")
        proc.poll.return_value = None  # always running
        proc.wait.return_value = None
        return proc

    fake_now = {"t": 1_000.0}

    def _fake_monotonic():
        return fake_now["t"]

    monkeypatch.setattr(
        "py_stremio.components.download.hls_ffmpeg_download.time.monotonic",
        _fake_monotonic,
    )

    def _advance():
        # Bump the clock on every readline() call so the stall check
        # in the while loop trips quickly.
        fake_now["t"] += 30.0

    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value="/usr/bin/ffmpeg",
    ), patch(
        "py_stremio.components.download.hls_ffmpeg_download.subprocess.Popen",
        side_effect=_stuck_factory,
    ):
        proc_holder = {}

        real_Popen = hls_ffmpeg_download.subprocess.Popen

        def _capturing_popen(*args, **kwargs):
            proc = real_Popen.return_value
            proc_holder["proc"] = proc
            return proc

        with patch(
            "py_stremio.components.download.hls_ffmpeg_download.subprocess.Popen",
            side_effect=lambda *a, **kw: (
                _capturing_popen(*a, **kw) or _stuck_factory(*a, **kw)
            ),
        ) as popen_mock:

            def _factory(cmd, **kw):
                proc = _stuck_factory(cmd, **kw)
                original_readline = proc.stdout.readline

                def _readline_then_advance(*a, **kw):
                    line = original_readline(*a, **kw)
                    _advance()
                    return line

                proc.stdout.readline = _readline_then_advance
                return proc

            popen_mock.side_effect = _factory
            downloader = HlsFfmpegDownloader(stall_timeout=10.0)
            with pytest.raises(HlsFfmpegStallError, match="no output for"):
                downloader.download("https://x.test/m.m3u8", str(target))


def test_download_rejects_output_smaller_than_min_size(tmp_path):
    """ffmpeg producing 100 bytes when MIN_COMPLETED_VIDEO_SIZE_MB=1
    must be rejected as an invalid video."""
    from py_stremio.components.configs import app_settings

    target = tmp_path / "show.mkv"
    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value="/usr/bin/ffmpeg",
    ), patch(
        "py_stremio.components.download.hls_ffmpeg_download.subprocess.Popen",
        side_effect=_fake_popen_success(output_bytes=b"\x00" * 100),
    ):
        original_min = app_settings.settings.MIN_COMPLETED_VIDEO_SIZE_MB
        app_settings.settings.MIN_COMPLETED_VIDEO_SIZE_MB = 1
        try:
            downloader = HlsFfmpegDownloader()
            with pytest.raises(HlsFfmpegError, match="only 100 bytes"):
                downloader.download("https://x.test/m.m3u8", str(target))
        finally:
            app_settings.settings.MIN_COMPLETED_VIDEO_SIZE_MB = original_min
    assert not target.exists()
    assert not (tmp_path / "show.mkv.part").exists()


def test_download_raises_when_ffmpeg_produces_no_output_file(tmp_path):
    """ffmpeg exits 0 but never created the .part file — surface that
    as a download error instead of leaving the caller wondering why
    the target is missing."""
    target = tmp_path / "show.mkv"

    def _factory(cmd, **_kw):
        proc = MagicMock()
        proc.stdout = io.StringIO("progress=end\n")
        proc.stderr = io.StringIO("")
        proc.poll.side_effect = [None, 0]
        proc.wait.return_value = 0
        return proc

    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value="/usr/bin/ffmpeg",
    ), patch(
        "py_stremio.components.download.hls_ffmpeg_download.subprocess.Popen",
        side_effect=_factory,
    ):
        downloader = HlsFfmpegDownloader()
        with pytest.raises(HlsFfmpegError, match="produced no output file"):
            downloader.download("https://x.test/m.m3u8", str(target))
    assert not target.exists()


def test_download_cleans_up_stale_part_file(tmp_path):
    """A leftover ``.part`` from a previous attempt must be removed
    before ffmpeg writes to the same path."""
    target = tmp_path / "show.mkv"
    partial = tmp_path / "show.mkv.part"
    partial.write_bytes(b"leftover bytes from a previous run")

    captured = {}

    def _factory(cmd, **_kw):
        captured["output"] = cmd[-1]
        Path(cmd[-1]).write_bytes(b"\x00" * 2048)
        proc = MagicMock()
        proc.stdout = io.StringIO("total_size=2048\nprogress=end\n")
        proc.stderr = io.StringIO("")
        proc.poll.side_effect = [None, 0]
        proc.wait.return_value = 0
        return proc

    with patch(
        "py_stremio.components.download.hls_ffmpeg_download.shutil.which",
        return_value="/usr/bin/ffmpeg",
    ), patch(
        "py_stremio.components.download.hls_ffmpeg_download.subprocess.Popen",
        side_effect=_factory,
    ):
        downloader = HlsFfmpegDownloader()
        size = downloader.download("https://x.test/m.m3u8", str(target))
    assert size == 2048
    assert target.stat().st_size == 2048


# ── warn_missing_ffmpeg ──────────────────────────────────────────────


def test_warn_missing_ffmpeg_emits_runtime_warning():
    with pytest.warns(RuntimeWarning, match="ffmpeg is not installed"):
        warn_missing_ffmpeg()


# ── Dispatcher: _download_hls_to_file ─────────────────────────────────


def test_dispatch_uses_ffmpeg_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "py_stremio.components.configs.app_settings.settings.HLS_DOWNLOAD_METHOD",
        "ffmpeg",
        raising=False,
    )
    target = tmp_path / "show.mkv"
    called = {"ffmpeg": 0, "segment": 0}

    class _StubFfmpeg:
        def __init__(self, **_kw):
            pass

        def download(self, url, filename):
            called["ffmpeg"] += 1
            Path(filename).write_bytes(b"\x00" * 1024)

    monkeypatch.setattr(
        "py_stremio.components.download.hls_ffmpeg_download.find_ffmpeg",
        lambda: "/usr/bin/ffmpeg",
    )
    monkeypatch.setattr(
        "py_stremio.components.download.hls_ffmpeg_download.HlsFfmpegDownloader",
        _StubFfmpeg,
    )

    real_segment_downloader = hls_download.HlsDownloader

    class _StubSegment:
        def __init__(self, **_kw):
            called.setdefault("segment_init", None)
            called["segment_init"] = True

        def download(self, url, filename):
            called["segment"] += 1
            Path(filename).write_bytes(b"\x00" * 1024)

        def close(self):
            pass

    monkeypatch.setattr(hls_download, "HlsDownloader", _StubSegment)

    _download_hls_to_file(
        url="https://x.test/1080p.m3u8",
        filename=str(target),
        bandwidth_limiter=None,
        thread_id=None,
        progress_callback=None,
        stall_timeout=60.0,
    )
    assert called["ffmpeg"] == 1
    assert called.get("segment", 0) == 0
    # Restore to keep other tests' behaviour.
    hls_download.HlsDownloader = real_segment_downloader


def test_dispatch_falls_back_to_segment_when_ffmpeg_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "py_stremio.components.configs.app_settings.settings.HLS_DOWNLOAD_METHOD",
        "ffmpeg",
        raising=False,
    )
    target = tmp_path / "show.mkv"
    monkeypatch.setattr(
        "py_stremio.components.download.hls_ffmpeg_download.find_ffmpeg",
        lambda: None,
    )

    class _StubSegment:
        def __init__(self, **_kw):
            self.kw = _kw

        def download(self, url, filename):
            Path(filename).write_bytes(b"\x00" * 1024)

        def close(self):
            pass

    monkeypatch.setattr(hls_download, "HlsDownloader", _StubSegment)

    with pytest.warns(RuntimeWarning, match="ffmpeg is not installed"):
        _download_hls_to_file(
            url="https://x.test/1080p.m3u8",
            filename=str(target),
            bandwidth_limiter=None,
            thread_id=None,
            progress_callback=None,
            stall_timeout=60.0,
        )
    assert target.exists()


def test_dispatch_falls_back_to_segment_on_ffmpeg_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "py_stremio.components.configs.app_settings.settings.HLS_DOWNLOAD_METHOD",
        "ffmpeg",
        raising=False,
    )
    target = tmp_path / "show.mkv"
    monkeypatch.setattr(
        "py_stremio.components.download.hls_ffmpeg_download.find_ffmpeg",
        lambda: "/usr/bin/ffmpeg",
    )

    class _StubFfmpeg:
        def __init__(self, **_kw):
            pass

        def download(self, url, filename):
            raise HlsFfmpegError("synthetic failure")

    monkeypatch.setattr(
        "py_stremio.components.download.hls_ffmpeg_download.HlsFfmpegDownloader",
        _StubFfmpeg,
    )

    class _StubSegment:
        def __init__(self, **_kw):
            pass

        def download(self, url, filename):
            Path(filename).write_bytes(b"\x00" * 1024)

        def close(self):
            pass

    monkeypatch.setattr(hls_download, "HlsDownloader", _StubSegment)

    with pytest.warns(RuntimeWarning, match="ffmpeg HLS download failed"):
        _download_hls_to_file(
            url="https://x.test/1080p.m3u8",
            filename=str(target),
            bandwidth_limiter=None,
            thread_id=None,
            progress_callback=None,
            stall_timeout=60.0,
        )
    assert target.exists()


def test_dispatch_uses_segment_when_method_explicitly_segment(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "py_stremio.components.configs.app_settings.settings.HLS_DOWNLOAD_METHOD",
        "segment",
        raising=False,
    )
    target = tmp_path / "show.mkv"
    ffmpeg_called = {"n": 0}

    class _ShouldNotBeCalled:
        def __init__(self, **_kw):
            pass

        def download(self, url, filename):
            ffmpeg_called["n"] += 1

    monkeypatch.setattr(
        "py_stremio.components.download.hls_ffmpeg_download.find_ffmpeg",
        lambda: "/usr/bin/ffmpeg",
    )
    monkeypatch.setattr(
        "py_stremio.components.download.hls_ffmpeg_download.HlsFfmpegDownloader",
        _ShouldNotBeCalled,
    )

    class _StubSegment:
        def __init__(self, **_kw):
            pass

        def download(self, url, filename):
            Path(filename).write_bytes(b"\x00" * 1024)

        def close(self):
            pass

    monkeypatch.setattr(hls_download, "HlsDownloader", _StubSegment)

    _download_hls_to_file(
        url="https://x.test/1080p.m3u8",
        filename=str(target),
        bandwidth_limiter=None,
        thread_id=None,
        progress_callback=None,
        stall_timeout=60.0,
    )
    assert ffmpeg_called["n"] == 0
    assert target.exists()


# ── download_stream_to_file dispatcher ───────────────────────────────


def test_download_stream_to_file_routes_m3u8_without_is_hls_flag(monkeypatch, tmp_path):
    """Any ``.m3u8`` URL should hit the HLS path even when the StreamInfo
    does NOT set ``is_hls=True``.  This is the change that makes
    RealDebrid-returned HLS manifests work without per-addon opt-in."""
    target = tmp_path / "show.mkv"
    monkeypatch.setattr(
        "py_stremio.components.configs.app_settings.settings.HLS_DOWNLOAD_METHOD",
        "segment",
        raising=False,
    )

    captured = {"called_with_url": None}

    class _StubSegment:
        def __init__(self, **_kw):
            pass

        def download(self, url, filename):
            captured["called_with_url"] = url
            Path(filename).write_bytes(b"\x00" * 1024)

        def close(self):
            pass

    monkeypatch.setattr(hls_download, "HlsDownloader", _StubSegment)

    download_stream_to_file(
        download_url="https://cdn.real-debrid.com/dl/abc/playlist.m3u8",
        filename=str(target),
        stream=StreamInfo(name="RD", url="https://cdn.real-debrid.com/dl/abc/playlist.m3u8", is_hls=False),
    )
    assert captured["called_with_url"] == "https://cdn.real-debrid.com/dl/abc/playlist.m3u8"


def test_download_stream_to_file_uses_ffmpeg_path_for_m3u8(monkeypatch, tmp_path):
    """End-to-end: a .m3u8 URL flows through to the ffmpeg downloader
    and produces the file on disk."""
    target = tmp_path / "show.mkv"
    monkeypatch.setattr(
        "py_stremio.components.configs.app_settings.settings.HLS_DOWNLOAD_METHOD",
        "ffmpeg",
        raising=False,
    )
    monkeypatch.setattr(
        "py_stremio.components.download.hls_ffmpeg_download.find_ffmpeg",
        lambda: "/usr/bin/ffmpeg",
    )
    monkeypatch.setattr(
        "py_stremio.components.download.hls_ffmpeg_download.HlsFfmpegDownloader",
        _RecorderFfmpeg := type(
            "_RecorderFfmpeg",
            (),
            {
                "__init__": lambda self, **kw: None,
                "download": lambda self, url, filename: Path(filename).write_bytes(b"\x00" * 2048),
            },
        ),
    )

    download_stream_to_file(
        download_url="https://hdhub.test/resolve/.../1080p.m3u8",
        filename=str(target),
    )
    assert target.exists()
    assert target.stat().st_size == 2048


def test_download_stream_to_file_does_not_route_non_hls_urls(monkeypatch, tmp_path):
    """A normal ``.mp4`` URL must NOT be sent through the HLS path —
    the new URL-only check should not regress the direct download."""
    target = tmp_path / "show.mkv"
    hls_called = {"n": 0}

    class _StubSegment:
        def __init__(self, **_kw):
            pass

        def download(self, url, filename):
            hls_called["n"] += 1

        def close(self):
            pass

    monkeypatch.setattr(hls_download, "HlsDownloader", _StubSegment)

    # Mock httpx to short-circuit a fake mp4 response.
    class _FakeResponse:
        status_code = 200
        headers = {"content-length": "1024", "content-type": "video/mp4"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size):
            yield b"\x00" * 1024

    class _FakeStream:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return _FakeResponse()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "py_stremio.components.download.stream_download.httpx.stream",
        _FakeStream,
    )

    download_stream_to_file(
        download_url="https://x.test/video.mp4",
        filename=str(target),
    )
    assert hls_called["n"] == 0
    assert target.exists()
