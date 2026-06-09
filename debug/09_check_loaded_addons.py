"""
Show exactly which addons are loaded (built-in vs file)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py_stremio.components.addons.factory import create_addon_manager
from dotenv import load_dotenv

load_dotenv()

print("Initializing addon manager...\n")
manager = create_addon_manager()

print(f"Total addons loaded: {len(manager.addons)}")
print(f"\nAddon list:")

# Group by category
from collections import defaultdict
categories = defaultdict(list)

for addon in manager.addons:
    addon_name = addon.__class__.__name__
    
    # Categorize by class name patterns
    if "Torrentio" in addon_name:
        categories["Torrentio Family"].append(addon_name)
    elif "Comet" in addon_name or "HDHub" in addon_name or "StremThru" in addon_name or "Guindex" in addon_name or "Brazuca" in addon_name:
        categories["Comet Family"].append(addon_name)
    elif "Anime" in addon_name or "Akuma" in addon_name or "OnePace" in addon_name or "Hanime" in addon_name:
        categories["Anime"].append(addon_name)
    elif "TV" in addon_name or "IPTV" in addon_name or "Skyflix" in addon_name or "Xtream" in addon_name:
        categories["IPTV/TV"].append(addon_name)
    elif "MediaFusion" in addon_name or "Knight" in addon_name or "ThePirateBay" in addon_name or "Peerflix" in addon_name or "Nucleus" in addon_name:
        categories["Aggregators"].append(addon_name)
    elif "Url" in addon_name or "Http" in addon_name:
        categories["URL/File-based"].append(addon_name)
    else:
        categories["Other"].append(addon_name)

for category, addons in sorted(categories.items()):
    print(f"\n{category} ({len(addons)}):")
    for addon_name in sorted(addons):
        print(f"  - {addon_name}")

print(f"\n{'='*60}")
print(f"Total: {len(manager.addons)} addons")
print(f"{'='*60}")
