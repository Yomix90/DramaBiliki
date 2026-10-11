import pytest
from bridge.streamer import StreamResolver

def test_m3u8_relative_url_rewrite():
    resolver = StreamResolver()
    base_url = "https://dramadunyam.com/vr/fr/vt/abc123xyz/"
    
    sample_m3u8 = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1463100,RESOLUTION=1080x1920
variant_1080p.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=805657,RESOLUTION=540x960
variant_540p.m3u8
"""
    rewritten = resolver.rewrite_m3u8(sample_m3u8, base_url=base_url)
    
    assert "https://dramadunyam.com/vr/fr/vt/abc123xyz/variant_1080p.m3u8" in rewritten
    assert "https://dramadunyam.com/vr/fr/vt/abc123xyz/variant_540p.m3u8" in rewritten

def test_m3u8_cdn_failover():
    resolver = StreamResolver()
    base_url = "https://cdn2.dramaflix.net/dfl-media/manifests/"
    
    sample_m3u8 = """#EXTM3U
#EXTINF:10.0,
https://cdn2.dramaflix.net/media/series/ep1/seg_001.ts?pexp=1790000000&psig=xyz
"""
    from bridge.config import settings
    original_primary = settings.SOURCE_CDN_PRIMARY
    try:
        settings.SOURCE_CDN_PRIMARY = "cdn.dramaflix.net"
        rewritten = resolver.rewrite_m3u8(sample_m3u8, base_url=base_url)
        assert "https://cdn.dramaflix.net/media/series/ep1/seg_001.ts" in rewritten
        assert "cdn2.dramaflix.net" not in rewritten
    finally:
        settings.SOURCE_CDN_PRIMARY = original_primary

def test_m3u8_segment_proxy():
    resolver = StreamResolver()
    base_url = "https://cdn.dramaflix.net/media/"
    bridge_base = "http://127.0.0.1:8000"
    
    sample_m3u8 = """#EXTM3U
#EXTINF:10.0,
seg_001.ts
"""
    rewritten = resolver.rewrite_m3u8(
        sample_m3u8,
        base_url=base_url,
        proxy_segments=True,
        bridge_base_url=bridge_base,
    )
    assert "http://127.0.0.1:8000/stream/seg?u=https%3A%2F%2Fcdn.dramaflix.net%2Fmedia%2Fseg_001.ts" in rewritten
