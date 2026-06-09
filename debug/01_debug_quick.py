"""
Quick test of Torrentio addon with RealDebrid key for 90 Day Fiance S33E05
"""
import httpx
import json
import os
from dotenv import load_dotenv

load_dotenv()

rd_key = os.getenv("REAL_DEBRID_API_KEY", "")
torrentio_base = f"https://torrentio.strem.fun/realdebrid={rd_key}"

imdb_id = "tt10955614"
season = 33
episode = 5
stremio_id = f"{imdb_id}:{season}:{episode}"

url = f"{torrentio_base}/stream/series/{stremio_id}.json"

print(f"Testing Torrentio for: {stremio_id}")
print(f"URL: {url[:80]}...")
print()

try:
    resp = httpx.get(url, timeout=10.0, follow_redirects=True)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(f"Streams found: {len(data.get('streams', []))}")
    if data.get('streams'):
        print("\nFirst 3 streams:")
        for stream in data['streams'][:3]:
            print(f"  - {stream.get('title', 'N/A')[:80]}")
    else:
        print("\nFull response:")
        print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error: {e}")
