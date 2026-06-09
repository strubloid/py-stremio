"""
Test all built-in and addons.txt addons using py-stremio's addon factory
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py_stremio.components.addons.factory import create_addon_manager
from py_stremio.components.stremio.stremio_ids import build_stremio_id
from dotenv import load_dotenv

load_dotenv()

# Initialize addon manager (loads built-in + addons.txt)
print("Initializing addon manager...")
manager = create_addon_manager()
print(f"Loaded {len(manager.addons)} addons\n")

# Target show
imdb_id = "tt10955614"
title = "90 Day Fiancé: Pillow Talk"
season = 33
episode = 5
type_ = "series"
stremio_id = build_stremio_id(imdb_id, title, season, episode)

print(f"Searching for: {stremio_id}")
print(f"Show: 90 Day Fiancé: Pillow Talk S33E05\n")

# Search all addons
streams_by_addon = {}
total_streams = 0

for addon in manager.addons:
    addon_name = addon.__class__.__name__
    try:
        streams = addon.get_streams(type_, stremio_id)
        if streams:
            streams_by_addon[addon_name] = streams
            total_streams += len(streams)
            print(f"✓ {addon_name}: {len(streams)} streams")
        else:
            print(f"✗ {addon_name}: 0 streams")
    except Exception as e:
        print(f"✗ {addon_name}: Error - {str(e)[:50]}")

print(f"\n{'='*60}")
print(f"TOTAL: {total_streams} streams from {len(streams_by_addon)} addons")
print(f"{'='*60}\n")

if streams_by_addon:
    print("Details of streams found:")
    for addon_name, streams in streams_by_addon.items():
        print(f"\n{addon_name}:")
        for idx, stream in enumerate(streams[:3], 1):  # Show first 3
            title = stream.get("title", "N/A")[:60]
            has_url = "url" in stream
            has_hash = "infoHash" in stream
            stream_type = "URL" if has_url else ("HASH" if has_hash else "OTHER")
            print(f"  {idx}. [{stream_type}] {title}")
