"""Tests for media file episode detection."""

from py_stremio.components.library.media_file import detect_existing_season_episodes, infer_next_episode_download
from py_stremio.utils.media import parse_episode_number


BLEACH_TYBW_S03_FILES = [
    "[Lazier] Bleach Thousand-Year Blood War - 27 (WEB 1080p EAC3) [8749C4A9].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 28 (WEB 1080p EAC3) [AC0C8A2A].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 29 (WEB 1080p EAC3) [7EF57884].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 30 (WEB 1080p EAC3) [2171F7D5].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 31 (WEB 1080p EAC3) [6F85B95C].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 32 (WEB 1080p EAC3) [E0BF7156].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 33 (WEB 1080p EAC3) [5016AD08].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 34 (WEB 1080p AAC) [EBDB3283].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 35 (WEB 1080p AAC) [C72E26CE].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 36 (WEB 1080p AAC) [E73FCD9F].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 37 (WEB 1080p AAC) [72E510BF].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 38 (WEB 1080p AAC) [CD3833B0].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 39 (WEB 1080p AAC) [A7BABE27].mkv",
    "[Lazier] Bleach Thousand-Year Blood War - 40 (WEB 1080p AAC) [E323D12D].mkv",
]


def test_parse_episode_number_prefers_release_dash_number_over_codec_and_crc_hashes():
    assert parse_episode_number("[Lazier] Bleach Thousand-Year Blood War - 32 (WEB 1080p EAC3) [E0BF7156].mkv") == 32
    assert parse_episode_number("[Lazier] Bleach Thousand-Year Blood War - 40 (WEB 1080p AAC) [E323D12D].mkv") == 40
    assert parse_episode_number("Show_S03E12.mkv") == 12
    assert parse_episode_number("episode 05.mkv") == 5


def test_absolute_numbered_bleach_season_maps_episodes_27_to_40_as_season_1_to_14(tmp_path):
    for filename in BLEACH_TYBW_S03_FILES:
        (tmp_path / filename).write_bytes(b"already downloaded")

    existing = detect_existing_season_episodes(tmp_path, episode_count=14)

    assert existing == set(range(1, 15))
    assert infer_next_episode_download(tmp_path, episode_count=14) == 15


def test_absolute_numbered_bleach_season_downloads_only_episode_15_when_metadata_grows(tmp_path):
    for filename in BLEACH_TYBW_S03_FILES:
        (tmp_path / filename).write_bytes(b"already downloaded")

    existing = detect_existing_season_episodes(tmp_path, episode_count=15)

    assert existing == set(range(1, 15))
    assert infer_next_episode_download(tmp_path, episode_count=15) == 15
