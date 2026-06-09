"""
Test 10 non-torrent/direct streaming addons
"""
import httpx
import json

# Direct streaming addons (not torrent aggregators)
direct_addons = [
    "https://vidfast-stream.cc",
    "https://plexio-stremio.plexio.stream",
    "https://easynews.strem.fun",
    "https://9acc0e1d93c4-premiumize.baby-beamup.club",
    "https://3d8e526d5a99-watchly.baby-beamup.club",
    "https://streailer.elfhosted.com",
    "https://shluflix.elfhosted.com",
    "https://annatar.elfhosted.com",
    "https://stream.dmm.moe",
    "https://watchhub.strem.fun",
]

imdb_id = "tt10955614"
season = 33
episode = 5
stremio_id = f"{imdb_id}:{season}:{episode}"

print(f"Testing {len(direct_addons)} direct streaming addons")
print(f"Target: {stremio_id} (90 Day Fiancé: Pillow Talk S33E05)\n")

results = {"found": 0, "empty": 0, "errors": 0}

for addon_url in direct_addons:
    addon_name = addon_url.split("//")[1].split(".")[0]
    stream_url = f"{addon_url}/stream/series/{stremio_id}.json"
    
    try:
        resp = httpx.get(stream_url, timeout=10.0, follow_redirects=True)
        data = resp.json()
        streams = data.get("streams", [])
        
        if streams:
            results["found"] += 1
            print(f"✓ {addon_name}: {len(streams)} streams")
            
            # Check stream type
            stream = streams[0]
            if "url" in stream:
                print(f"    Type: Direct URL")
            elif "infoHash" in stream:
                print(f"    Type: Torrent")
            elif "externalUrl" in stream:
                print(f"    Type: External (browser redirect)")
            else:
                print(f"    Type: Unknown")
            print(f"    Title: {stream.get('title', 'N/A')[:50]}")
        else:
            results["empty"] += 1
            print(f"✗ {addon_name}: 0 streams")
            
    except httpx.TimeoutException:
        results["errors"] += 1
        print(f"✗ {addon_name}: Timeout")
    except json.JSONDecodeError:
        results["errors"] += 1
        print(f"✗ {addon_name}: Invalid JSON")
    except httpx.HTTPStatusError as e:
        results["errors"] += 1
        print(f"✗ {addon_name}: HTTP {e.response.status_code}")
    except Exception as e:
        results["errors"] += 1
        print(f"✗ {addon_name}: {str(e)[:40]}")
    
    print()

print(f"{'='*60}")
print(f"Results: {results['found']} found, {results['empty']} empty, {results['errors']} errors")
print(f"{'='*60}")
