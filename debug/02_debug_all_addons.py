"""
Test all configured addon servers from download-config.json
"""
import httpx
import json

# Addon servers from the show's download-config.json
addon_servers = [
    "https://torrentio.strem.fun",
    "https://comet.elfhosted.com",
    "https://cometnet.site",
    "https://torz.strem.fun",
    "https://stremify.erzen.tk",
    "https://public.stremthru.com",
    "https://v3-cinemeta.strem.io",
    "https://vidfast-stream.cc"
]

imdb_id = "tt10955614"
season = 33
episode = 5
stremio_id = f"{imdb_id}:{season}:{episode}"

print(f"Testing {len(addon_servers)} addons for: {stremio_id}\n")

for addon_url in addon_servers:
    stream_url = f"{addon_url}/stream/series/{stremio_id}.json"
    
    try:
        resp = httpx.get(stream_url, timeout=10.0, follow_redirects=True)
        data = resp.json()
        streams = data.get("streams", [])
        
        status = "✓" if streams else "✗"
        print(f"{status} {addon_url}")
        print(f"   Status: {resp.status_code}, Streams: {len(streams)}")
        
        if streams:
            print(f"   First stream: {streams[0].get('title', 'N/A')[:60]}")
        
    except httpx.TimeoutException:
        print(f"✗ {addon_url}")
        print(f"   Timeout")
    except Exception as e:
        print(f"✗ {addon_url}")
        print(f"   Error: {str(e)[:60]}")
    
    print()
