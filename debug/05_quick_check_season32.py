"""
Test Season 32 episodes on major aggregators
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py_stremio.components.addons.types import TorrentioAddon, MediaFusionAddon, ThePirateBayPlusAddon
from py_stremio.components.stremio.stremio_ids import build_stremio_id
from dotenv import load_dotenv

load_dotenv()

rd_key = os.getenv("REAL_DEBRID_API_KEY", "")

# Test Season 32 Episode 1
imdb_id = "tt10955614"
title = "90 Day Fiancé: Pillow Talk"
season = 32
episode = 1
stremio_id = build_stremio_id(imdb_id, title, season, episode)

print(f"Testing Season 32 Episode 1: {stremio_id}")
print(f"Show: 90 Day Fiancé: Pillow Talk S32E01\n")

addons = [
    ("Torrentio", TorrentioAddon()),
    ("MediaFusion", MediaFusionAddon()),
    ("ThePirateBay+", ThePirateBayPlusAddon()),
]

for name, addon in addons:
    print(f"Testing {name}...")
    try:
        streams = addon.get_streams(stremio_id)
        if streams:
            print(f"  ✓ Found {len(streams)} streams")
            print(f"    First: {streams[0].get('title', 'N/A')[:60]}")
        else:
            print(f"  ✗ No streams found")
    except Exception as e:
        print(f"  ✗ Error: {str(e)[:60]}")
    print()
