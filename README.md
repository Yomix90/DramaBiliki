# 🎬 DramaBiliki — Vertical Mini-Drama Streaming Platform

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Flutter](https://img.shields.io/badge/Flutter-3.47+-02569B.svg)](https://flutter.dev/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**DramaBiliki** is a high-performance streaming platform for short vertical dramas (in the style of *DramaWave*, *ReelShort*, *ShortMax*, and *NetShort*). It consists of a resilient Python/FastAPI **Bridge Server** and a native **Flutter Mobile App** with TikTok/ReelShort vertical swipe navigation.

---

## 🏛️ System Architecture

```
┌────────────────────────┐
│  Source CMS & Origin   │
│  (dramadunyam.com)     │
└───────────┬────────────┘
            │ 1. Polite Incremental Sync (Semaphore = 2, Jitter, dd_bilet cookie)
            ▼
┌────────────────────────┐
│      BRIDGE (VPS)      │  ◄── SQLite (SQLAlchemy 2.0)
│   (Python / FastAPI)   │  ◄── In-Memory Stream Cache (TTL ≤ 10 min)
│                        │  ◄── HLS Rewrite & CDN Failover (cdn2 ↔ cdn)
│                        │  ◄── Bootstrap 5 Admin Panel (/admin)
└───────────┬────────────┘
            │ 2. Clean REST API (/api/v1) & HLS Master Playlist (/stream)
            ▼
┌────────────────────────┐
│   Flutter Mobile App   │  ◄── Riverpod State Management & Dio
│ (Android & iOS native) │  ◄── TikTok/ReelShort Vertical Video Player
│                        │  ◄── Multilingual i18n (AR / FR / EN) & Full RTL
└────────────────────────┘
```

> [!IMPORTANT]
> The mobile application **never communicates directly with the source site**. All metadata, authentication, media caching, and real-time streaming manifest resolution are mediated by the Bridge.

---

## 🚀 Part 1: Bridge Server

### Features
- **Polite Crawler / Sync**: Concurrency bounded to 2 simultaneous requests, random jitter delay, exponential backoff retries, and automatic `dd_bilet` cookie renewal.
- **Media Optimization**: Covers and thumbnails are downloaded, converted to WebP with 300px and 600px width variants, and served locally at `/media/covers/{id}.webp`.
- **Dynamic HLS Resolver**:
  - Fetches upstream playlists on-the-fly (`/hls/{id}/{ep}/playlist.m3u8`).
  - Rewrites relative paths into absolute URLs.
  - Implements automatic CDN failover (`cdn2.dramaflix.net` ↔ `cdn.dramaflix.net`).
  - Generates HLS wrappers for direct MP4 sources.
  - Short in-memory caching bounded by signed expiration timestamps (`pexp` / `Expires`).
- **REST API v1**: Complete endpoints for Home Feed (Banners, Trending, New Releases, Continue Watching), Catalog Search, Detail, Library (Favorites & Progress), and Subtitles.
- **Web Admin Dashboard**: Built-in Bootstrap 5 admin panel at `/admin` to monitor sync runs, toggle series status, manage banners, and edit metadata.
- **Background Scheduler**: Automated light sync (every 30 mins) and full catalog sync (daily).

### Prerequisites
- Python 3.11+
- SQLite3

### Setup & Local Run

```bash
# 1. Clone repository
git clone https://github.com/Yomix90/DramaBiliki.git
cd DramaBiliki

# 2. Create virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
```

### Initial Synchronization

```bash
# Sync a specific series by slug
python -m bridge.sync --series rejected-by-my-mate-marked-by-the-alpha-queen

# Run a light sync (first pages for latest series and episodes)
python -m bridge.sync --light --pages 2

# Run a full catalog sync
python -m bridge.sync --full --pages 15
```

### Starting the Bridge

```bash
# Launch server via Uvicorn
python -m bridge
# or
uvicorn bridge.api.app:app --host 0.0.0.0 --port 8000 --reload
```

- **OpenAPI Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Web Admin Dashboard**: [http://localhost:8000/admin](http://localhost:8000/admin)

### Running Bridge Tests

```bash
pip install -r requirements-dev.txt
pytest tests -v   # uses an isolated temporary database
```

---

## 📱 Part 2: Flutter Mobile Application

### Features
- **TikTok / ReelShort Vertical Player**:
  - Vertical swipe (`PageView`) between episodes (Swipe Up = Next Ep, Swipe Down = Prev Ep).
  - Instant auto-play and pre-loading of upcoming episodes.
  - Interactive scrubbing seekbar with duration overlays.
  - Double-tap gesture to play/pause.
  - Playback speed selector (`0.75x`, `1.0x`, `1.25x`, `1.5x`, `2.0x`).
  - Subtitles toggle (`CC`) and quick episode picker bottom sheet.
  - Periodic progress sync to Bridge (`/api/v1/history/progress`).
- **Modern Dark UI**: Deep blacks, coral crimson accents (`#FF2E55`), smooth hero banners carousel, horizontal categorized shelves.
- **Full Multilingual & RTL**: Instant switching between **English (EN)**, **Français (FR)**, and **العربية (AR)** with complete RTL layout adaptation.
- **My Library**: Tracks favorites and watch history with progress bars and one-tap resume.
- **Offline Resilient**: Local storage via `SharedPreferences`, cached network images, and graceful retry states.

### Running & Building the Mobile App

```bash
cd mobile

# 1. Install Flutter dependencies
flutter pub get

# 2. Run unit and widget tests
flutter test

# 3. Run on connected Android / iOS device or emulator
flutter run

# 4. Build Release APK for Android
flutter build apk --release
# Output: mobile/build/app/outputs/flutter-apk/app-release.apk
```

---

## 🌐 Part 3: VPS Deployment with Dokploy (recommended)

The repository ships a production `Dockerfile` (non-root user, healthcheck, persistent
volumes) and a Dokploy-compatible `docker-compose.yml`. Dokploy builds it from GitHub and
Traefik serves it over HTTPS.

### 1. Create the service
1. In Dokploy: **Create Project → Create Service → Application**.
2. **Provider**: GitHub → repository `Yomix90/DramaBiliki`, branch `main`.
3. **Build Type**: `Dockerfile` (path `./Dockerfile`, context `.`).
4. Enable **Autodeploy** so every push to `main` redeploys.

> Prefer Compose? Choose **Compose** instead, file `docker-compose.yml`: same variables and volumes.

### 2. Environment variables (Environment tab)

```env
SECRET_KEY=<openssl rand -hex 32>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<a strong password>
PUBLIC_BASE_URL=https://api.your-domain.com
```

Everything else has production defaults (see `.env.example`). The default admin password
is **refused** in production; if `SECRET_KEY` is missing, a random one is generated and
stored in the data volume.

### 3. Persistent volumes (Advanced → Volumes)

| Type | Volume name | Mount path |
|------|-------------|------------|
| Volume mount | `dramabiliki-data` | `/app/data` (SQLite DB + secret) |
| Volume mount | `dramabiliki-media` | `/app/media` (cached WebP covers) |

Use *volume* mounts (not bind mounts): the container runs as uid 1000.

### 4. Domain (Domains tab)
Host `api.your-domain.com`, **container port `8090`**, HTTPS on with Let's Encrypt.
Point the DNS `A` record of that host to your VPS IP.

### 5. Deploy & check
- `https://api.your-domain.com/health` → `{"status":"healthy"}`
- `https://api.your-domain.com/admin` → login page
- On an empty database the first light sync starts automatically after boot
  (follow it in **Admin → Synchronisation**), then every 30 min + a full sync daily.

### 6. Point the mobile app to the server
In the app: **Profile → Server Bridge URL** → `https://api.your-domain.com`, or change
`defaultBaseUrl` in `mobile/lib/core/constants.dart` before building the release APK.

### Notes
- Run **a single process/worker**: the scheduler and the sync lock live in-process.
- Behind Traefik, URLs (covers, HLS) are generated with `https://` thanks to proxy headers;
  `PUBLIC_BASE_URL` forces the value if needed.

### Alternative: plain Docker / systemd
```bash
docker compose up -d --build      # needs ADMIN_PASSWORD in the environment or .env
```
With systemd, run `python -m bridge` (one worker) behind Nginx forwarding
`Host` and `X-Forwarded-Proto`.

---

## 🔒 Security & Best Practices

- **SSRF Mitigation**: The Bridge strictly validates all proxy segment requests against an approved whitelist (`dramadunyam.com`, `dramaflix.net`, and upstream CDN endpoints).
- **Ephemeral URL Protection**: Signed CDN URLs (`pexp`/`Expires`) are never permanently stored in the database.
- **Device Authentication**: Secure stateless JWT issued per device (`/api/v1/auth/device`) with future extensibility for OAuth (Google/Apple).
- **Admin Panel**: Login required (signed HttpOnly session cookie, SameSite=strict, same-origin check on every action, lockout after 5 failed attempts per IP).
- **Secrets**: The public default `SECRET_KEY` / `ADMIN_PASSWORD` are never used in production.

---

## 📄 License
This project is licensed under the MIT License.
