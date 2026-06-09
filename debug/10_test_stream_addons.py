"""
Filter and test only stream-providing addons (exclude subtitles/catalogs/metadata)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py_stremio.components.addons.factory import create_addon_manager
from py_stremio.components.stremio_ids import build_stremio_id
from dotenv import load_dotenv

load_dotenv()

# Keywords to identify non-stream addons
NON_STREAM_KEYWORDS = [
    "subtitle", "sub", "opensubtitle", "addic7ed", "napisy", "subscene", 
    "podnapisi", "yify", "catalog", "imdb", "tmdb", "rpdb", "trakt", 
    "rating", "marvel", "concert", "netflix", "serializd", "simkl", 
    "rotten", "radio", "broadcast", "upnext", "collection"
]

def is_stream_addon(addon_name: str) -> bool:
    """Check if addon likely provides video streams (not just subtitles/catalogs)"""
    name_lower = addon_name.lower()
    return not any(keyword in name_lower for keyword in NON_STREAM_KEYWORDS)

print("Initializing addon manager...")
manager = create_addon_manager()

# Filter to stream-providing addons
stream_addons = [a for a in manager.addons if is_stream_addon(a.__class__.__name__)]

print(f"Total addons loaded: {len(manager.addons)}")
print(f"Stream-providing addons: {len(stream_addons)}")
print(f"Non-stream addons filtered out: {len(manager.addons) - len(stream_addons)}\n")

imdb_id = "tt10955614"
season = 33
episode = 5
stremio_id = build_stremio_id(imdb_id, season, episode)

print(f"Testing {len(stream_addons)} stream addons for: {stremio_id}\n")

results = {"found": 0, "empty": 0, "errors": 0}
streams_found = []

for idx, addon in enumerate(stream_addons, 1):
    addon_name = addon.__class__.__name__
    
    if idx % 10 == 0:
        print(f"Progress: {idx}/{len(stream_addons)}")
    
    try:
        streams = addon.get_streams(stremio_id)
        if streams:
            results["found"] += 1
            streams_found.append((addon_name, streams))
            print(f"✓ {addon_name}: {len(streams)} streams")
        else:
            results["empty"] += 1
    except Exception as e:
        results["errors"] += 1

print(f"\n{'='*60}")
print(f"Results: {results['found']} found, {results['empty']} empty, {results['errors']} errors")
print(f"{'='*60}\n")

if streams_found:
    print("Streams found:")
    for addon_name, streams in streams_found:
        print(f"\n{addon_name} ({len(streams)} streams):")
        for idx, stream in enumerate(streams[:3], 1):
            print(f"  {idx}. {stream.get('title', 'N/A')[:70]}")
