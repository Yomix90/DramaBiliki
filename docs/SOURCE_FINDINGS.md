# 🔍 Source Findings & Technical Audit — dramadunyam.com

**Date of Audit**: October 2026  
**Audited Target**: `https://dramadunyam.com/` and media distribution CDN `dramaflix.net` / upstream CDNs  
**Tools used**: `curl 8.21.0`, `httpx`, Python 3.14, direct live HTTP inspections  

---

## 1. Executive Summary & Verification vs `RAPPORT_ANALYSE_ETAPE0.md`

Live HTTP analysis of `dramadunyam.com` confirms the core streaming architecture described in the initial analysis report, with critical nuances and real-world mechanisms discovered during testing:

| Feature / Endpoint | Report Description | Live Observed Reality | Bridge Implementation Strategy |
|---|---|---|---|
| **Session & Cloudflare Protection** | Cloudflare edge, open API | Cloudflare WAF + `dd_bilet` cookie required for `/api/*` and `/hls/*`. Without this cookie, calls return `412 {"error":"bilet"}`. | The Bridge client initializes by calling `/api/config` or `/`, retaining the `dd_bilet` cookie (valid 12h) with an identifiable Browser User-Agent. |
| **Catalog Listing** | Not fully documented in report | Dedicated paginated endpoint `/api/series?type=tumu&page=N&limit=48&lang=en` containing over 37,400+ series across 37+ platforms (ShortMax, NetShort, DramaBox, ReelShort, DramaWave, etc.). | Bridge scanner queries `/api/series` with pagination and syncs metadata, tags, and covers incrementally. |
| **Series Metadata** | `/api/series/{slug}?lang=` includes episodes array | `/api/series/{slug}?lang=` returns full metadata: `id`, `slug`, `title`, `description`, `cover`, `cover_variants` (160–1080px), `total_episodes`, `available_episodes`, `genre`, `tags`, `platform`, `similar`. Episode count is explicit. | Bridge stores metadata in database and queries/indexes episodes 1 to `available_episodes`. |
| **HLS Entrypoint (`/hls/{id}/{ep}/playlist.m3u8`)** | HTTP 302 redirect towards CDN | Confirmed: returns `302 Found` with `Location` header. Target URL depends on the source platform. | The Bridge handles all 3 target formats transparently. |
| **Media Stream Formats** | HLS M3U8 with signed tokens `pexp`/`psig` on `cdn2`/`cdn.dramaflix.net` | Three distinct distribution models observed:<br>1. **HLS Master/Media on dramaflix.net**: (e.g. series 229665) Manifest on `dramaflix.net`, segments signed with expiration.<br>2. **Direct HLS on dramadunyam.com**: (e.g. series 130631) Redirects to `/vr/fr/vt/.../master.m3u8` with multi-bitrate relative variants (1080p, 720p, etc.) and fMP4 segments.<br>3. **Direct signed MP4**: (e.g. DramaBox series 319823) Redirects to signed CloudFront/CDN URL (`.mp4`) with `Expires` token (~24h). | Bridge normalizes all stream types: rewrites relative M3U8 paths to absolute, applies CDN failover (`cdn2` ↔ `cdn`), wraps or serves direct MP4s in a unified stream endpoint for the mobile player. |
| **Subtitles** | `/api/subtitles/{id}/{ep}?lang=` | Returns JSON dialogue cues or WebVTT cues (or `[]` if hardcoded/dubbed). | Bridge provides `/api/v1/subtitles/{id}/{ep}?lang=` returning standardized WebVTT (.vtt). |

---

## 2. Detailed Technical Findings

### 2.1 The `dd_bilet` Session Mechanism
Requests made directly without session initialization:
```http
GET /api/series?type=tumu&page=1&limit=5 HTTP/1.1
Host: dramadunyam.com
User-Agent: curl/8.21.0

HTTP/1.1 412 Precondition Failed
{"error":"bilet"}
```

When fetching `https://dramadunyam.com/api/config` or `/`:
```http
HTTP/1.1 200 OK
Set-Cookie: dd_bilet=1791785833.0.qxsU27MvdmJ8wfOvQDTR1ww5klgyfXaxgLlHNfzDvkA; Path=/; Max-Age=43200; HttpOnly; SameSite=Lax; Secure
```
With the `dd_bilet` cookie stored and standard browser headers supplied, all REST APIs and stream redirection endpoints return HTTP 200 / 302 without captcha or challenge.

### 2.2 Streaming Redirection Analysis

#### Case A: HLS with External Cloud Storage (e.g., ShortWave)
- URL: `GET /hls/229665/2/playlist.m3u8`
- 302 Redirect to: `https://dramaflix.net/dfl-media/manifests/shortwave/e02949d7487a308f23392b4cfd3aaee3.m3u8?expires=1791755976`
- Manifest content: Contains `.ts` segments signed with `X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Expires=21600` (~6h validity).
- Segments support CORS: `access-control-allow-origin: *`.

#### Case B: Multi-bitrate HLS with Relative URIs (e.g., Series 130631)
- URL: `GET /hls/130631/1/playlist.m3u8`
- 302 Redirect to: `/vr/fr/vt/dc890025-641c-4fd3-a6e3-567fcaaa99e6/h264-...m3u8`
- Master playlist contains:
  ```m3u8
  #EXT-X-STREAM-INF:BANDWIDTH=1463100,RESOLUTION=1080x1920
  1_5aa...adaptiveDynamicStreaming_1301549_0.m3u8
  #EXT-X-STREAM-INF:BANDWIDTH=1117817,RESOLUTION=720x1280
  1_5aa...adaptiveDynamicStreaming_1301549_1.m3u8
  ```
- **Crucial Requirement for Bridge**: The mobile player expects absolute URLs. The Bridge must rewrite relative paths (`1_5aa...m3u8`) to point to the resolved absolute origin (`https://dramadunyam.com/vr/fr/vt/...`) or proxy through the Bridge.

#### Case C: Direct High-Quality MP4 Stream (e.g., DramaBox Series 319823)
- URL: `GET /hls/319823/1/playlist.m3u8`
- 302 Redirect to: `https://hwztvideo.dramaboxdb.com/.../701679689.720p.wz.h264.encrypt.mp4?Expires=...&Signature=...`
- Returns HTTP 200 with `Content-Type: video/mp4`, `Accept-Ranges: bytes`, 20MB length.
- Plays directly in mobile video player or wrapped in an HLS manifest.

---

## 3. Bridge Architecture Implications

1. **Session-Aware Fetcher**:
   The Bridge uses an asynchronous HTTP client pool (`httpx.AsyncClient`) with automatic cookie persistence, periodic cookie renewal via `/api/config`, and proper User-Agent headers.

2. **Unified Stream Resolution**:
   The endpoint `/stream/{series_id}/{ep}/master.m3u8`:
   - Follows the upstream 302 redirection.
   - If response is an HLS playlist: rewrites relative URLs into absolute URLs, replaces failing CDN hosts (`cdn2` ↔ `cdn`) if needed, and sets `Cache-Control: max-age=600`.
   - If response is a direct video (`.mp4`), either redirects the client directly or generates an on-the-fly HLS wrapper manifest with a single `#EXTINF` segment pointing to the signed MP4 URL.

3. **In-Memory Manifest Cache**:
   Avoids overloading the source server. TTL is calculated dynamically based on `pexp` or `Expires` parameter (max 10 minutes).

4. **Polite Scanner**:
   - Concurrency bounded to 2 simultaneous requests.
   - Jittered delay between catalog pages (0.5s - 1.5s).
   - Incremental sync checking `available_episodes` against database records.
