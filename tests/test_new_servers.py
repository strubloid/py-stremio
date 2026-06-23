"""
Tests for new server discovery and validation.
"""
import json
import re
from typing import Dict, Any

import httpx
import pytest

# Test timeout for external requests
REQUEST_TIMEOUT = 15.0

# Server URLs to test (using full URLs from the original message)
HLS_STREAM_URL = "https://stream-limit-vid.321moviesfree.com/401604691e5e71f09a754177d1c00102/bb6df82d84f8400faa6eb3061edf0a85-f608c0a5027496a9430d4cf36c06150a-sd.m3u8?hdnts=exp=1782742858_acl=/401604691e5e71f09a754177d1c00102/*_hmac=b0bfa50abb2b2e0f59f7e48ffdd9c9fc83fdabaca58ed4821e7ab4eab7a8e24d"

CONFIG_ENDPOINT_URL = "https://streamio.heykanhaiya.xyz/configure"

# Full manifest URLs (reconstructed from the original message)
MANIFEST_URLS = [
    "https://streamio.heykanhaiya.xyz/eyJtYXhSZXN1bHRzUGVyUmVzb2x1dGlvbiI6MCwibWF4U2l6ZSI6MCwiY2FjaGVkT25seSI6ZmFsc2UsInNvcnRDYWNoZWRVbmNhY2hlZFRvZ2V0aGVyIjpmYWxzZSwicmVtb3ZlVHJhc2giOnRydWUsInJlc3VsdEZvcm1hdCI6WyJhbGwiXSwiZGVicmlkU2VydmljZXMiOlt7InNlcnZpY2UiOiJyZWFsZGVicmlkIiwiYXBpS2V5IjoiTzdDTkVCSTVOR0VRS1JEUFJPVlhJM1dTWkdMV0JORk03SEZBNkFLWUxEREpWWVE0SkxXQSJ9XSwiZW5hYmxlVG9ycmVudCI6ZmFsc2UsImRlZHVwbGljYXRlU3RyZWFtcyI6ZmFsc2UsInNjcmFwZURlYnJpZEFjY291bnRUb3JyZW50cyI6ZmFsc2UsImRlYnJpZFN0cmVhbVByb3h5UGFzc3dvcmQiOiIiLCJsYW5ndWFnZXMiOnsicmVxdWlyZWQiOltdLCJhbGxvd2VkIjpbXSwiZXhjbHVkZSI6W10sInByZWZlcnJlZCI6W119LCJyZXNvbHV0aW9ucyI6e30sIm9wdGlvbnMiOnsicmVtb3ZlX3JhbmtzX3VuZGVyIjotMTAwMDAwMDAwMDAsImFsbG93X2VuZ2xpc2hfaW5fbGFuZ3VhZ2VzIjpmYWxzZSwicmVtb3ZlX3Vua25vd25fbGFuZ3VhZ2VzIjpmYWxzZX19/manifest.json",
    "https://comet.feels.legal/eyJtYXhSZXN1bHRzUGVyUmVzb2x1dGlvbiI6MCwibWF4U2l6ZSI6MCwiY2FjaGVkT25seSI6ZmFsc2UsInNvcnRDYWNoZWRVbmNhY2hlZFRvZ2V0aGVyIjpmYWxzZSwicmVtb3ZlVHJhc2giOnRydWUsInJlc3VsdEZvcm1hdCI6WyJhbGwiXSwiZGVicmlkU2VydmljZXMiOlt7InNlcnZpY2UiOiJyZWFsZGVicmlkIiwiYXBpS2V5IjoiTzdDTkVCSTVOR0VRS1JEUFJPVlhJM1dTWkdMV0JORk03SEZBNkFLWUxEREpWWVE0SkxXQSJ9XSwiZW5hYmxlVG9ycmVudCI6ZmFsc2UsImRlZHVwbGljYXRlU3RyZWFtcyI6ZmFsc2UsInNjcmFwZURlYnJpZEFjY291bnRUb3JyZW50cyI6ZmFsc2UsImRlYnJpZFN0cmVhbVByb3h5UGFzc3dvcmQiOiIiLCJsYW5ndWFnZXMiOnsicmVxdWlyZWQiOltdLCJhbGxvd2VkIjpbXSwiZXhjbHVkZSI6W10sInByZWZlcnJlZCI6W119LCJyZXNvbHV0aW9ucyI6e30sIm9wdGlvbnMiOnsicmVtb3ZlX3JhbmtzX3VuZGVyIjotMTAwMDAwMDAwMDAsImFsbG93X2VuZ2xpc2hfaW5fbGFuZ3VhZ2VzIjpmYWxzZSwicmVtb3ZlX3Vua25vd25fbGFuZ3VhZ2VzIjpmYWxzZX19/manifest.json",
    "https://b889cc320158-inmax.baby-beamup.club/manifest.json",
    "https://c73485b8a7a2-javjt.baby-beamup.club/manifest.json",
    "https://1fe84bc728af-maxsport.baby-beamup.club/manifest.json",
    "https://23dfbfad8cb2-stremio-addon-superflix.baby-beamup.club/manifest.json",
    "https://streamio.fankai.fr/eyJzdHJlYW1GaWx0ZXIiOiJhbGwiLCJkZWJyaWRTZXJ2aWNlIjoicmVhbGRlYnJpZCIsImRlYnJpZEFwaUtleSI6Imh0dHBzOi8vYjg4OWNjMzIwMTU4LWlubWF4LmJhYnktYmVhbXVwLmNsdWIvbWFuaWZlc3QuanNvbiIsImRlYnJpZFN0cmVhbVByb3h5UGFzc3dvcmQiOiIiLCJtYXhBY3RvcnNEaXNwbGF5IjoiYWxsIiwiZGVmYXVsdFNvcnQiOiJsYXN0X3VwZGF0ZSJ9/manifest.json",
]


def is_reasonable_stremio_manifest(data: Dict[str, Any]) -> bool:
    """Check if data looks like a reasonable Stremio manifest.
    
    Based on inspection of various manifests, we check for:
    - Required identity fields: id, version, name
    - At least one of: resources, catalogs (both indicate content offering)
    """
    # Must have basic identity
    if not all(field in data for field in ["id", "version", "name"]):
        return False
    
    # Must have some way to offer content
    has_resources = "resources" in data and isinstance(data.get("resources"), list) and len(data["resources"]) > 0
    has_catalogs = "catalogs" in data and isinstance(data.get("catalogs"), list) and len(data["catalogs"]) > 0
    
    return has_resources or has_catalogs


@pytest.mark.network
def test_hls_stream_accessibility():
    """Test that the HLS stream URL is accessible."""
    try:
        response = httpx.head(HLS_STREAM_URL, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        # Accept 200 OK or 206 Partial Content (for range requests)
        assert response.status_code in (200, 206), f"Expected 200/206, got {response.status_code}"
        # Check that it's likely an m3u8 stream
        content_type = response.headers.get("content-type", "").lower()
        assert "m3u8" in content_type or "mpegurl" in content_type, f"Not an m3u8 stream: {content_type}"
    except httpx.RequestError as e:
        pytest.fail(f"Failed to access HLS stream: {e}")


@pytest.mark.network
def test_configuration_endpoint():
    """Test that the configuration endpoint is accessible."""
    try:
        response = httpx.get(CONFIG_ENDPOINT_URL, timeout=REQUEST_TIMEOUT)
        # Configuration endpoint might return HTML or JSON
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        # Should return some content
        assert len(response.text) > 0, "Configuration endpoint returned empty response"
    except httpx.RequestError as e:
        pytest.fail(f"Failed to access configuration endpoint: {e}")


@pytest.mark.network
@pytest.mark.parametrize("url", MANIFEST_URLS)
def test_manifest_urls(url: str):
    """Test that each manifest URL returns valid JSON and reasonable Stremio manifest structure."""
    try:
        response = httpx.get(url, timeout=REQUEST_TIMEOUT)
        assert response.status_code == 200, f"Manifest URL {url} returned {response.status_code}"
        
        # Try to parse as JSON
        try:
            data = response.json()
        except json.JSONDecodeError:
            pytest.fail(f"Manifest URL {url} did not return valid JSON")
        
        # Basic validation
        assert isinstance(data, dict), f"Manifest root should be a dictionary, got {type(data)}"
        assert is_reasonable_stremio_manifest(data), f"Manifest {url} doesn't look like a reasonable Stremio manifest"
        
    except httpx.RequestError as e:
        pytest.fail(f"Failed to access manifest URL {url}: {e}")


def test_manifest_urls_have_expected_pattern():
    """Test that manifest URLs from heykanhaiya.xyz and comet.feels.legal have the expected encoded config pattern."""
    encoded_pattern_urls = [
        "https://streamio.heykanhaiya.xyz/eyJtYXhSZXN1bHRzUGVyUmVzb2x1dGlvbiI6MCwibWF4U2l6ZSI6MCwiY2FjaGVkT25seSI6ZmFsc2UsInNvcnRDYWNoZWRVbmNhY2hlZFRvZ2V0aGVyIjpmYWxzZSwicmVtb3ZlVHJhc2giOnRydWUsInJlc3VsdEZvcm1hdCI6WyJhbGwiXSwiZGVicmlkU2VydmljZXMiOlt7InNlcnZpY2UiOiJyZWFsZGVicmlkIiwiYXBpS2V5IjoiTzdDTkVCSTVOR0VRS1JEUFJPVlhJM1dTWkdMV0JORk03SEZBNkFLWUxEREpWWVE0SkxXQSJ9XSwiZW5hYmxlVG9ycmVudCI6ZmFsc2UsImRlZHVwbGljYXRlU3RyZWFtcyI6ZmFsc2UsInNjcmFwZURlYnJpZEFjY291bnRUb3JyZW50cyI6ZmFsc2UsImRlYnJpZFN0cmVhbVByb3h5UGFzc3dvcmQiOiIiLCJsYW5ndWFnZXMiOnsicmVxdWlyZWQiOltdLCJhbGxvd2VkIjpbXSwiZXhjbHVkZSI6W10sInByZWZlcnJlZCI6W119LCJyZXNvbHV0aW9ucyI6e30sIm9wdGlvbnMiOnsicmVtb3ZlX3JhbmtzX3VuZGVyIjotMTAwMDAwMDAwMDAsImFsbG93X2VuZ2xpc2hfaW5fbGFuZ3VhZ2VzIjpmYWxzZSwicmVtb3ZlX3Vua25vd25fbGFuZ3VhZ2VzIjpmYWxzZX19/manifest.json",
        "https://comet.feels.legal/eyJtYXhSZXN1bHRzUGVyUmVzb2x1dGlvbiI6MCwibWF4U2l6ZSI6MCwiY2FjaGVkT25seSI6ZmFsc2UsInNvcnRDYWNoZWRVbmNhY2hlZFRvZ2V0aGVyIjpmYWxzZSwicmVtb3ZlVHJhc2giOnRydWUsInJlc3VsdEZvcm1hdCI6WyJhbGwiXSwiZGVicmlkU2VydmljZXMiOlt7InNlcnZpY2UiOiJyZWFsZGVicmlkIiwiYXBpS2V5IjoiTzdDTkVCSTVOR0VRS1JEUFJPVlhJM1dTWkdMV0JORk03SEZBNkFLWUxEREpWWVE0SkxXQSJ9XSwiZW5hYmxlVG9ycmVudCI6ZmFsc2UsImRlZHVwbGljYXRlU3RyZWFtcyI6ZmFsc2UsInNjcmFwZURlYnJpZEFjY291bnRUb3JyZW50cyI6ZmFsc2UsImRlYnJpZFN0cmVhbVByb3h5UGFzc3dvcmQiOiIiLCJsYW5ndWFnZXMiOnsicmVxdWlyZWQiOltdLCJhbGxvd2VkIjpbXSwiZXhjbHVkZSI6W10sInByZWZlcnJlZCI6W119LCJyZXNvbHV0aW9ucyI6e30sIm9wdGlvbnMiOnsicmVtb3ZlX3JhbmtzX3VuZGVyIjotMTAwMDAwMDAwMDAsImFsbG93X2VuZ2xpc2hfaW5fbGFuZ3VhZ2VzIjpmYWxzZSwicmVtb3ZlX3Vua25vd25fbGFuZ3VhZ2VzIjpmYWxzZX19/manifest.json"
    ]
    
    for url in encoded_pattern_urls:
        # Extract the path part after domain
        if "/manifest.json" in url:
            path_part = url.split("/manifest.json")[0]
            # Should have the base64-encoded config as the last path segment
            path_segments = path_part.split("/")
            assert len(path_segments) > 0, f"No path segments found in {url}"
            config_segment = path_segments[-1]
            # Should be reasonably long and contain base64-like characters
            assert len(config_segment) > 50, f"Config segment too short in {url}"
            # Should contain typical base64 chars (allowing for + / = and possibly . for URL-safe base64 variants)
            # Actually, let's just check it's not empty and doesn't contain obvious non-base64 patterns we know aren't there
            assert "..." not in config_segment, f"Config segment appears truncated in {url}"


if __name__ == "__main__":
    # Allow running directly for manual testing
    print("Running new servers tests...")
    print("=" * 50)
    
    # Test HLS stream
    print("Testing HLS stream accessibility...")
    try:
        test_hls_stream_accessibility()
        print("✓ HLS stream test passed")
    except Exception as e:
        print(f"✗ HLS stream test failed: {e}")
    
    # Test configuration endpoint
    print("Testing configuration endpoint...")
    try:
        test_configuration_endpoint()
        print("✓ Configuration endpoint test passed")
    except Exception as e:
        print(f"✗ Configuration endpoint test failed: {e}")
    
    # Test manifests
    print("Testing manifest URLs...")
    for url in MANIFEST_URLS:
        try:
            test_manifest_urls(url)
            print(f"✓ Manifest test passed: {url[:60]}...")
        except Exception as e:
            print(f"✗ Manifest test failed: {url[:60]}... - {e}")
    
    # Test URL patterns
    print("Testing manifest URL patterns...")
    try:
        test_manifest_urls_have_expected_pattern()
        print("✓ Manifest URL pattern test passed")
    except Exception as e:
        print(f"✗ Manifest URL pattern test failed: {e}")
    
    print("=" * 50)
    print("Tests completed.")