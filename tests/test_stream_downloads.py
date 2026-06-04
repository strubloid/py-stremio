"""Tests for stream download resume behavior."""

from py_stremio.components import stream_downloads


class FakeResponse:
    status_code = 206
    headers = {"content-length": "6", "content-range": "bytes 4-9/10"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self, chunk_size=8192):
        yield b"ef"
        yield b"ghij"


def test_download_stream_to_file_resumes_existing_partial_part_file(tmp_path, monkeypatch):
    # Disable the minimum file size check for this test (uses small test data)
    monkeypatch.setattr(stream_downloads.settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 0)
    target = tmp_path / "episode.mkv"
    partial = tmp_path / "episode.mkv.part"
    partial.write_bytes(b"abcd")
    captured = {}

    def fake_stream(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(stream_downloads.httpx, "stream", fake_stream)

    progress_events = []
    stream_downloads.download_stream_to_file(
        "https://example.test/video.mkv",
        str(target),
        progress_callback=lambda downloaded, total: progress_events.append((downloaded, total)),
    )

    assert captured["headers"]["Range"] == "bytes=4-"
    assert target.read_bytes() == b"abcdefghij"
    assert not partial.exists()
    assert progress_events[-1] == (10, 10)
