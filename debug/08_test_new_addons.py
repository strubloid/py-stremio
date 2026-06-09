"""
Test all 144+ addons after running --discover
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py_stremio.components.addons.factory import create_addon_manager
from py_stremio.components.stremio_ids import build_stremio_id
from dotenv import load_dotenv
import time

load_dotenv()

print("Initializing addon manager...")
manager = create_addon_manager()
print(f"Loaded {len(manager.addons)} addons\n")

imdb_id = "tt10955614"
season = 33
episode = 5
stremio_id = build_stremio_id(imdb_id, season, episode)

print(f"Searching for: {stremio_id}")
print(f"Show: 90 Day Fiancé: Pillow Talk S33E05\n")

results = {"success": 0, "empty": 0, "errors": 0}
streams_found = []

start_time = time.time()

for idx, addon in enumerate(manager.addons, 1):
    addon_name = addon.__class__.__name__
    
    # Progress indicator every 10 addons
    if idx % 10 == 0:
        elapsed = time.time() - start_time
        print(f"Progress: {idx}/{len(manager.addons)} ({elapsed:.1f}s)")
    
    try:
        streams = addon.get_streams(stremio_id)
        if streams:
            results["success"] += 1
            streams_found.append((addon_name, streams))
            print(f"✓ {addon_name}: {len(streams)} streams")
        else:
            results["empty"] += 1
    except Exception as e:
        results["errors"] += 1
        error_msg = str(e)[:40]
        if results["errors"] <= 5:  # Only show first 5 errors
            print(f"✗ {addon_name}: {error_msg}")

elapsed = time.time() - start_time

print(f"\n{'='*60}")
print(f"COMPLETED in {elapsed:.1f}s")
print(f"Total: {results['success']} with streams, {results['empty']} empty, {results['errors']} errors")
print(f"{'='*60}\n")

if streams_found:
    print("Streams found from these addons:")
    for addon_name, streams in streams_found:
        print(f"\n{addon_name} ({len(streams)} streams):")
        for idx, stream in enumerate(streams[:2], 1):
            title = stream.get("title", "N/A")[:60]
            has_url = "url" in stream
            has_hash = "infoHash" in stream
            stream_type = "URL" if has_url else ("HASH" if has_hash else "OTHER")
            print(f"  {idx}. [{stream_type}] {title}")
else:
    print("No streams found from any addon.")
