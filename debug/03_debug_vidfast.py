"""
Inspect VidFast stream details to see what type it is
"""
import httpx
import json

addon_url = "https://vidfast-stream.cc"
imdb_id = "tt10955614"
season = 33
episode = 5
stremio_id = f"{imdb_id}:{season}:{episode}"

stream_url = f"{addon_url}/stream/series/{stremio_id}.json"

print(f"Testing VidFast for: {stremio_id}")
print(f"URL: {stream_url}\n")

try:
    resp = httpx.get(stream_url, timeout=10.0, follow_redirects=True)
    data = resp.json()
    streams = data.get("streams", [])
    
    print(f"Status: {resp.status_code}")
    print(f"Streams found: {len(streams)}\n")
    
    if streams:
        print("Full stream data:")
        print(json.dumps(streams[0], indent=2))
        print("\nStream type analysis:")
        stream = streams[0]
        if "url" in stream:
            print(f"  ✓ Has 'url' field (direct HTTP download)")
        if "infoHash" in stream:
            print(f"  ✓ Has 'infoHash' field (torrent)")
        if "externalUrl" in stream:
            print(f"  ✓ Has 'externalUrl' field (browser redirect - NOT downloadable)")
        if "ytId" in stream:
            print(f"  ✓ Has 'ytId' field (YouTube video)")
            
except Exception as e:
    print(f"Error: {e}")
