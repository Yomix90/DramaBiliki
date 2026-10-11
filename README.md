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
pytest tests -v
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

## 🌐 Part 3: VPS Deployment (Systemd + Nginx + Certbot)

### 1. Systemd Service

Create `/etc/systemd/system/dramabiliki.service`:

```ini
[Unit]
Description=DramaBiliki Bridge Service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/DramaBiliki
Environment="PATH=/var/www/DramaBiliki/venv/bin"
ExecStart=/var/www/DramaBiliki/venv/bin/uvicorn bridge.api.app:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable dramabiliki
sudo systemctl start dramabiliki
```

### 2. Nginx Reverse Proxy with HTTPS

Create `/etc/nginx/sites-available/dramabiliki`:

```nginx
server {
    server_name api.dramabiliki.yourdomain.com;

    # Gzip Compression
    gzip on;
    gzip_types text/plain application/json application/vnd.apple.mpegurl application/x-mpegURL text/vtt;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 60s;
        proxy_read_timeout 120s;
    }

    # Cache static WebP covers
    location /media/ {
        proxy_pass http://127.0.0.1:8000;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }
}
```

Enable site and generate SSL certificate:
```bash
sudo ln -s /etc/nginx/sites-available/dramabiliki /etc/nginx/sites-enabled/
sudo certbot --nginx -d api.dramabiliki.yourdomain.com
```

### 3. Docker Deployment (Alternative)

```bash
docker compose up -d --build
```

---

## 🔒 Security & Best Practices

- **SSRF Mitigation**: The Bridge strictly validates all proxy segment requests against an approved whitelist (`dramadunyam.com`, `dramaflix.net`, and upstream CDN endpoints).
- **Ephemeral URL Protection**: Signed CDN URLs (`pexp`/`Expires`) are never permanently stored in the database.
- **Device Authentication**: Secure stateless JWT issued per device (`/api/v1/auth/device`) with future extensibility for OAuth (Google/Apple).

---

## 📄 License
This project is licensed under the MIT License.
