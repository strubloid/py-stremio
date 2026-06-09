"""
Verify IMDb metadata from Cinemeta API
"""
import httpx
import json

imdb_id = "tt10955614"
cinemeta_url = f"https://v3-cinemeta.strem.io/meta/series/{imdb_id}.json"

print(f"Fetching metadata for IMDb: {imdb_id}")
print(f"URL: {cinemeta_url}\n")

try:
    resp = httpx.get(cinemeta_url, timeout=10.0, follow_redirects=True)
    data = resp.json()
    meta = data.get("meta", {})
    
    print(f"Title: {meta.get('name', 'N/A')}")
    print(f"Type: {meta.get('type', 'N/A')}")
    print(f"Genre: {', '.join(meta.get('genre', []))}")
    print(f"Year: {meta.get('year', 'N/A')}")
    print(f"IMDb ID: {meta.get('id', 'N/A')}")
    print(f"IMDb Rating: {meta.get('imdbRating', 'N/A')}")
    print(f"Description: {meta.get('description', 'N/A')[:100]}...")
    
    videos = meta.get("videos", [])
    print(f"\nTotal episodes: {len(videos)}")
    
    # Count episodes per season
    seasons = {}
    for video in videos:
        season = video.get("season", 0)
        seasons[season] = seasons.get(season, 0) + 1
    
    print(f"Total seasons: {len(seasons)}")
    print(f"\nEpisodes per season:")
    for season_num in sorted(seasons.keys()):
        print(f"  Season {season_num}: {seasons[season_num]} episodes")
    
    # Check if S33E05 exists
    print(f"\nLooking for Season 33 Episode 5...")
    s33e05 = [v for v in videos if v.get("season") == 33 and v.get("episode") == 5]
    if s33e05:
        ep = s33e05[0]
        print(f"  ✓ Found: {ep.get('title', 'N/A')}")
        print(f"    Released: {ep.get('released', 'N/A')}")
    else:
        print(f"  ✗ Not found in metadata")
    
except Exception as e:
    print(f"Error: {e}")
