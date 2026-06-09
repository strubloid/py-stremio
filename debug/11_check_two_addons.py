"""
Inspect actual stream content from CometNet and Jackettio to see if they're real or advisory
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py_stremio.components.addons.factory import create_addon_manager
from py_stremio.components.stremio_ids import build_stremio_id
from dotenv import load_dotenv
import json

load_dotenv()

manager = create_addon_manager()

# Find CometNet and Jackettio addons
target_addons = []
for addon in manager.addons:
    addon_name = addon.__class__.__name__
    if "CometNet" in addon_name or "Jackettio" in addon_name:
        target_addons.append((addon_name, addon))

if not target_addons:
    print("Could not find CometNet or Jackettio addons")
    sys.exit(1)

imdb_id = "tt10955614"
season = 33
episode = 5
stremio_id = build_stremio_id(imdb_id, season, episode)

print(f"Inspecting streams from {len(target_addons)} addons for: {stremio_id}\n")

for addon_name, addon in target_addons:
    print(f"{'='*60}")
    print(f"Addon: {addon_name}")
    print(f"{'='*60}\n")
    
    try:
        streams = addon.get_streams(stremio_id)
        
        if not streams:
            print("No streams returned\n")
            continue
        
        print(f"Streams returned: {len(streams)}\n")
        
        for idx, stream in enumerate(streams[:3], 1):
            print(f"Stream #{idx}:")
            print(json.dumps(stream, indent=2))
            print()
            
            # Analyze stream type
            print("Analysis:")
            if "url" in stream:
                print(f"  ✓ Has 'url': {stream['url'][:80]}...")
                print(f"    → This is a direct HTTP download URL")
            elif "infoHash" in stream:
                print(f"  ✓ Has 'infoHash': {stream['infoHash']}")
                print(f"    → This is a torrent magnet link")
            elif "externalUrl" in stream:
                print(f"  ✓ Has 'externalUrl': {stream['externalUrl'][:80]}...")
                print(f"    → This is a browser redirect (NOT downloadable)")
            else:
                print(f"  ✗ No url/infoHash/externalUrl")
                print(f"    → This might be an advisory message")
            
            title = stream.get("title", "")
            name = stream.get("name", "")
            description = stream.get("description", "")
            
            # Check for advisory keywords
            advisory_keywords = ["configure", "install", "setup", "debrid", "provider", "required", "enable"]
            combined_text = f"{title} {name} {description}".lower()
            
            if any(keyword in combined_text for keyword in advisory_keywords):
                print(f"  ⚠ Contains advisory keywords (configure/setup/debrid/provider)")
                print(f"    → This is likely NOT a real video stream")
            
            print()
        
    except Exception as e:
        print(f"Error: {e}\n")
