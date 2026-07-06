# Asetify — Music Player (FastAPI + Vanilla JS)

Pemutar musik ala Spotify. **Tanpa Spotify Premium & tanpa API key.**

- **Metadata** → [SpotAPI](https://github.com/Aran404/SpotAPI) — katalog Spotify (search, artis, album, playlist, "Fans also like") via API privat, tanpa login.
- **Audio** → [spotmate.online](https://spotmate.online) (primer) + [spowload.cc](https://spowload.cc) (fallback) — konversi URL track Spotify → **MP3 langsung** (`audio/mpeg`), kompatibel semua browser termasuk iOS.
- **Lirik** → [Lyrica](https://github.com/Wilooper/Lyrica) (7 sumber) dengan fallback **LRCLIB** — LRC ber-sinkron.

```
asetify-starter/
├── main.py            # FastAPI: SpotAPI + spotmate + lirik
├── requirements.txt
└── static/
    ├── index.html     # player (Tailwind + vanilla JS, PWA)
    ├── sw.js          # service worker (offline shell)
    ├── manifest.webmanifest
    └── icon-*.png
```

## Fitur
- 🔎 Pencarian **lagu + artis + album + playlist**; klik artis → halaman artis, klik album/playlist → daftar lagunya.
- ▶️ Player penuh: play/pause, next/prev, seek, **volume + mute**, mode repeat/shuffle, keyboard shortcut, Media Session (kontrol lockscreen HP).
- ♾️ **Autoplay/Radio** — antrean otomatis dari algoritma "Fans also like" Spotify.
- 🎚️ **Panel Antrean** — lihat, reorder (drag / ▲▼), hapus, "Add to queue".
- 🎤 **Lirik ber-sinkron** yang ikut lagu.
- 📱 **PWA** — installable + offline app shell.

## Endpoint
| Endpoint | Fungsi |
|----------|--------|
| `GET /api/explore?type=global\|trending_id\|trending_yogya` | daftar lagu per kategori |
| `GET /api/search?q=` | lagu + artis + album + playlist |
| `GET /api/album?id=` / `GET /api/playlist_tracks?id=` | isi album / playlist |
| `GET /api/artist?id=` | top tracks artis |
| `GET /api/radio?artist_id=&seed=` | auto-queue (radio) |
| `GET /api/resolve?url=<spotify track url>` | → `{streamUrl}` MP3 dari spotmate |
| `GET /api/lyrics?artist=&title=` | lirik (Lyrica / LRCLIB) |

## Setup
```bash
cd asetify-starter
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000   # buka http://<ip>:8000
```
Tidak perlu API key, cookies, ffmpeg, atau Deno.

### Lirik penuh (opsional)
Jalankan Lyrica sebagai sidecar agar lirik pakai 7 sumber (tanpa ini, lirik tetap jalan via LRCLIB):
```bash
cd /root/Lyrica && python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/gunicorn -c gunicorn.config.py -b 127.0.0.1:9999 run:app
```
Arahkan app: `export LYRICA_URL=http://127.0.0.1:9999`.

## Deployment (produksi — seperti yang berjalan sekarang)
Tiga systemd service + Cloudflare Tunnel untuk HTTPS di domain sendiri.

| Service | Peran | Bind |
|---------|-------|------|
| `asetify` | app utama (uvicorn) | `127.0.0.1:8000` |
| `lyrica` | lirik (gunicorn) | `127.0.0.1:9999` |
| `cloudflared` | tunnel HTTPS → domain | → Cloudflare |

```bash
systemctl status asetify lyrica cloudflared   # cek
systemctl restart asetify                       # setelah edit kode
journalctl -u asetify -f                         # log
```

**Cloudflare Tunnel** (HTTPS tanpa buka port, PWA installable):
```bash
cloudflared tunnel create asetify
cloudflared tunnel route dns asetify <domain-kamu>
# ~/.cloudflared/config.yml -> ingress: hostname <domain> -> service http://localhost:8000
cloudflared service install && systemctl start cloudflared
```

## Cara kerja `/api/resolve` (audio)
`spotmate.online` = konverter Spotify→MP3. Implementasi (`spotmate_convert`):
1. GET homepage → ambil session + `csrf-token` (**sesi dipakai ulang**, refresh hanya bila gagal).
2. POST `/convert` dengan `x-csrf-token` + `{"urls": <spotify url>}` → dapat URL MP3 dari `rapid.dlapi.app`.
3. Hasil di-**cache per lagu (30 mnt)**; panggilan di-serialize agar tak nge-burst (anti-abuse).

Browser memutar URL MP3 itu langsung (tidak lewat server, tidak IP-lock).

**Fallback spowload.cc** (dipakai bila spotmate gagal): pola identik dengan spotmate —
GET homepage (csrf + sesi Laravel, **dipakai ulang**), lalu POST `/convert` `{urls}` →
URL MP3 dari `rapid.dlapi.app`. Anti-abuse sama: sesi reuse, hasil di-cache, serialize.
Tidak butuh token manual / CAPTCHA.

## Catatan
- ⚠️ **Legal / edukasi**: SpotAPI (endpoint privat Spotify) & spotmate (downloader pihak ketiga) melanggar ToS masing-masing. Untuk belajar/personal, bukan produksi publik.
- spotmate service pihak ketiga — kalau down/berubah, `/api/resolve` bisa gagal (404). Jaga volume rendah agar Cloudflare-nya tak mulai menantang.
