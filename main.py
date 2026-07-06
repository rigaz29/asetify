"""
Asetify Starter — backend FastAPI.

Stack:
  - Metadata  -> SpotAPI (katalog Spotify, TANPA Premium / TANPA API key)
  - Audio     -> spotmate.online (konversi URL Spotify -> MP3 langsung, audio/mpeg)
  - Lirik     -> Lyrica / LRCLIB

Jalankan: uvicorn main:app --host 0.0.0.0 --port 8000
"""

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import spotapi
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Asetify Starter API (SpotAPI + spotmate)")


# ---------------------------------------------------------------------------
# SpotAPI — metadata (tanpa Premium, tanpa API key; search publik tanpa login)
# ---------------------------------------------------------------------------
def fmt_track(data: dict) -> dict | None:
    uri = (data or {}).get("uri", "")
    if "track" not in uri:                             # terima Track dari search/album/playlist
        return None
    tid = uri.split(":")[-1]                           # spotify:track:ID -> ID
    arts = (data.get("artists") or {}).get("items") or []
    artist = ", ".join((a.get("profile") or {}).get("name", "") for a in arts if a)
    album = data.get("albumOfTrack") or {}
    sources = (album.get("coverArt") or {}).get("sources") or []
    cover = max(sources, key=lambda s: s.get("width", 0)).get("url", "") if sources else ""
    return {
        "id": tid,
        "title": data.get("name"),
        "artist": artist,
        "artistId": (arts[0] or {}).get("uri", "").split(":")[-1] if arts else "",
        "album": album.get("name", ""),
        "cover": cover,
        "url": f"https://open.spotify.com/track/{tid}" if tid else "",
    }


def search_tracks(query: str, limit: int = 30) -> list[dict]:
    try:
        page = next(iter(spotapi.Public.song_search(query)), [])   # halaman pertama
    except Exception as e:
        raise HTTPException(502, f"SpotAPI error: {e}")
    out = []
    for entry in page:
        t = fmt_track(entry.get("item", {}).get("data", {}))
        if t:
            out.append(t)
        if len(out) >= limit:
            break
    return out


EXPLORE = {
    "global": "top hits 2025",
    "trending_id": "lagu indonesia terpopuler 2025",
    "trending_yogya": "lagu jawa",
}


@app.get("/api/explore")
def explore(type: str = Query("global")):
    return search_tracks(EXPLORE.get(type, EXPLORE["global"]))


def _img(sources: list) -> str:
    return max(sources, key=lambda s: s.get("width", 0)).get("url", "") if sources else ""


def _fmt_artist(d: dict) -> dict:
    d = d or {}
    vi = (d.get("visualIdentity") or {}).get("squareCoverImage") or {}
    return {"type": "artist", "id": (d.get("uri") or "").split(":")[-1],
            "name": (d.get("profile") or {}).get("name", ""),
            "cover": _img(vi.get("sources") or [])}


def _fmt_album(d: dict) -> dict:
    d = d or {}
    arts = (d.get("artists") or {}).get("items") or []
    return {"type": "album", "id": (d.get("uri") or "").split(":")[-1],
            "name": d.get("name", ""),
            "artist": ", ".join((a.get("profile") or {}).get("name", "") for a in arts if a),
            "cover": _img((d.get("coverArt") or {}).get("sources") or [])}


def _fmt_playlist(d: dict) -> dict:
    d = d or {}
    imgs = (d.get("images") or {}).get("items") or []
    return {"type": "playlist", "id": (d.get("uri") or "").split(":")[-1],
            "name": d.get("name", ""),
            "owner": ((d.get("ownerV2") or {}).get("data") or {}).get("name", ""),
            "cover": _img((imgs[0].get("sources") or []) if imgs else [])}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1)):
    """Cari lagu + artis + album + playlist sekaligus (satu panggilan searchDesktop)."""
    try:
        sv = spotapi.Song().query_songs(q, limit=8)["data"]["searchV2"]
    except Exception as e:
        raise HTTPException(502, f"SpotAPI error: {e}")

    def sec(name):
        return (sv.get(name) or {}).get("items") or []

    tracks = [t for t in (fmt_track(((e or {}).get("item") or {}).get("data") or {}) for e in sec("tracksV2")) if t]
    artists = [a for a in (_fmt_artist((e or {}).get("data")) for e in sec("artists")) if a["id"]]
    albums = [a for a in (_fmt_album((e or {}).get("data")) for e in sec("albumsV2")) if a["id"]]
    playlists = [p for p in (_fmt_playlist((e or {}).get("data")) for e in sec("playlists")) if p["id"]]
    return {"tracks": tracks, "artists": artists, "albums": albums, "playlists": playlists}


@app.get("/api/album")
def album(id: str = Query(...)):
    """Daftar lagu dalam sebuah album."""
    out = []
    try:
        for page in spotapi.Public.album_info(id):
            for it in page:
                t = fmt_track(it.get("track") or {})
                if t:
                    out.append(t)
            break
    except Exception as e:
        raise HTTPException(502, f"SpotAPI error: {e}")
    return out


@app.get("/api/playlist_tracks")
def playlist_tracks(id: str = Query(...)):
    """Daftar lagu dalam sebuah playlist."""
    out = []
    try:
        for page in spotapi.Public.playlist_info(id):
            for it in page.get("items", []):
                t = fmt_track(it.get("itemV2", {}).get("data", {}))
                if t:
                    out.append(t)
            break
    except Exception as e:
        raise HTTPException(502, f"SpotAPI error: {e}")
    return out


def _artist_top_tracks(artist_union: dict) -> list[dict]:
    items = artist_union.get("discography", {}).get("topTracks", {}).get("items", [])
    return [t for t in (fmt_track(it.get("track") or {}) for it in items) if t]


def _artist_overview(artist_id: str) -> dict:
    """Ambil artistUnion pakai client hangat dari pool (thread-safe, dipakai ulang)."""
    client = spotapi.client_pool.get()
    try:
        return spotapi.Artist(client=client).get_artist(artist_id)["data"]["artistUnion"]
    finally:
        spotapi.client_pool.put(client)


def _fetch_artist_top(artist_id: str, n: int = 3) -> list[dict]:
    try:
        return _artist_top_tracks(_artist_overview(artist_id))[:n]
    except Exception:
        return []


@app.get("/api/radio")
def radio(artist_id: str = Query(...), seed: str = Query(None), limit: int = Query(20)):
    """Auto-queue ala Spotify: top tracks artis seed + 'Fans also like'
    (relatedArtists), diambil paralel lalu di-dedup & di-shuffle."""
    import random

    try:
        au = _artist_overview(artist_id)
    except Exception as e:
        raise HTTPException(502, f"SpotAPI error: {e}")

    pool: dict[str, dict] = {}

    def add(tracks: list[dict]):
        for t in tracks:
            if t.get("id") and t["id"] != seed:
                pool.setdefault(t["id"], t)

    add(_artist_top_tracks(au))                                    # artis seed
    related = au.get("relatedContent", {}).get("relatedArtists", {}).get("items", [])
    random.shuffle(related)
    ids = [ra.get("id") or ra.get("uri", "").split(":")[-1] for ra in related[:6]]
    ids = [i for i in ids if i]

    with ThreadPoolExecutor(max_workers=6) as ex:                  # paralel -> cepat
        for tracks in ex.map(_fetch_artist_top, ids):
            add(tracks)

    out = list(pool.values())
    random.shuffle(out)
    return out[:limit]


@app.get("/api/artist")
def artist(id: str = Query(...)):
    """Top tracks seorang artis — untuk 'halaman artis' saat kartu artis diklik."""
    try:
        return _artist_top_tracks(_artist_overview(id))
    except Exception as e:
        raise HTTPException(502, f"SpotAPI error: {e}")


@app.get("/api/playlist")
def playlist():
    return search_tracks(EXPLORE["global"])


# ---------------------------------------------------------------------------
# Audio: spotmate.online — konversi URL Spotify -> MP3 langsung (audio/mpeg)
# ---------------------------------------------------------------------------
_SPOTMATE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# Satu sesi dipakai ulang (meniru 1 browser), + cache hasil per track.
_spotmate_lock = threading.Lock()
_spotmate = {"client": None, "csrf": None}
_spotmate_cache: dict[str, tuple[str, float]] = {}   # track_id -> (mp3_url, kedaluwarsa)
SPOTMATE_CACHE_TTL = 1800                             # 30 menit


def _spotmate_new_session():
    """Buka homepage sekali -> dapat cookies sesi + csrf-token. Sesi dipakai ulang."""
    client = httpx.Client(timeout=25, follow_redirects=True, headers={"user-agent": _SPOTMATE_UA})
    try:
        page = client.get("https://spotmate.online/en1")
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', page.text)
        if not m:
            client.close()
            return None, None
        return client, m.group(1)
    except Exception:
        client.close()
        return None, None


def spotmate_convert(spotify_url: str, track_id: str = "") -> str | None:
    """Konversi URL track Spotify -> URL MP3 (audio/mpeg) via spotmate.online.
    Sesi dipakai ulang & di-refresh hanya bila gagal; hasil di-cache per lagu."""
    now = time.time()
    if track_id:
        hit = _spotmate_cache.get(track_id)
        if hit and hit[1] > now:
            return hit[0]

    with _spotmate_lock:                              # serial -> tidak nge-burst
        for _ in range(2):                            # coba sesi lama, refresh sekali bila gagal
            client, csrf = _spotmate["client"], _spotmate["csrf"]
            if client is None:
                client, csrf = _spotmate_new_session()
                if client is None:
                    return None
                _spotmate["client"], _spotmate["csrf"] = client, csrf
            try:
                resp = client.post("https://spotmate.online/convert",
                                   headers={"content-type": "application/json",
                                            "x-csrf-token": csrf,
                                            "referer": "https://spotmate.online/en1",
                                            "accept": "*/*"},
                                   json={"urls": spotify_url})
                if resp.status_code == 200:
                    data = resp.json()
                    if not data.get("error") and data.get("url"):
                        url = data["url"]
                        if track_id:
                            _spotmate_cache[track_id] = (url, now + SPOTMATE_CACHE_TTL)
                        return url
            except Exception:
                pass
            # gagal (419/sesi mati/dll) -> buang sesi, ulang sekali dengan sesi baru
            try:
                client.close()
            except Exception:
                pass
            _spotmate["client"], _spotmate["csrf"] = None, None
    return None


# --- Fallback: spowload.cc (sama pola dengan spotmate: CSRF + sesi Laravel) ---
_spowload_lock = threading.Lock()
_spowload = {"client": None, "csrf": None}
_spowload_cache: dict[str, tuple[str, float]] = {}


def _spowload_new_session():
    client = httpx.Client(timeout=25, follow_redirects=True, headers={"user-agent": _SPOTMATE_UA})
    try:
        page = client.get("https://spowload.cc/")
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', page.text)
        if not m:
            client.close()
            return None, None
        return client, m.group(1)
    except Exception:
        client.close()
        return None, None


def spowload_convert(spotify_url: str, track_id: str = "") -> str | None:
    """Fallback konverter Spotify->MP3 via spowload.cc. Anti-abuse sama dengan spotmate:
    sesi dipakai ulang (refresh bila gagal), hasil di-cache, panggilan di-serialize."""
    now = time.time()
    if track_id:
        hit = _spowload_cache.get(track_id)
        if hit and hit[1] > now:
            return hit[0]
    with _spowload_lock:
        for _ in range(2):
            client, csrf = _spowload["client"], _spowload["csrf"]
            if client is None:
                client, csrf = _spowload_new_session()
                if client is None:
                    return None
                _spowload["client"], _spowload["csrf"] = client, csrf
            try:
                resp = client.post("https://spowload.cc/convert",
                                   headers={"content-type": "application/json",
                                            "x-csrf-token": csrf,
                                            "referer": "https://spowload.cc/",
                                            "accept": "*/*"},
                                   json={"urls": spotify_url})
                if resp.status_code == 200:
                    data = resp.json()
                    if not data.get("error") and data.get("url"):
                        url = data["url"]
                        if track_id:
                            _spowload_cache[track_id] = (url, now + SPOTMATE_CACHE_TTL)
                        return url
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
            _spowload["client"], _spowload["csrf"] = None, None
    return None


@app.get("/api/resolve")
def resolve(url: str = Query(...)):
    tid = url.rstrip("/").split("/")[-1].split("?")[0]

    sm_url = spotmate_convert(url, tid)                   # PRIMER
    if sm_url:
        return {"success": True, "streamUrl": sm_url, "source": "spotmate", "full": True}

    sw_url = spowload_convert(url, tid)                   # FALLBACK
    if sw_url:
        return {"success": True, "streamUrl": sw_url, "source": "spowload", "full": True}

    raise HTTPException(404, "Sumber audio tidak tersedia saat ini. Coba lagu lain.")


# ---------------------------------------------------------------------------
# Lirik: Lyrica (utama, bila service jalan) + LRCLIB (fallback langsung)
# ---------------------------------------------------------------------------
LYRICA_URL = os.getenv("LYRICA_URL", "http://127.0.0.1:9999")


def _lyrics_from_lyrica(artist: str, title: str) -> dict | None:
    try:
        r = httpx.get(f"{LYRICA_URL}/lyrics/",
                      params={"artist": artist, "song": title, "timestamps": "true"},
                      timeout=20)
        j = r.json()
        if j.get("status") == "success":
            data = j.get("data", {})
            if data.get("lyrics"):
                return {"synced": bool(data.get("hasTimestamps")),
                        "source": f"lyrica:{data.get('source', '')}",
                        "lyrics": data["lyrics"]}
    except Exception:
        pass
    return None


def _lyrics_from_lrclib(artist: str, title: str) -> dict | None:
    try:
        arr = httpx.get("https://lrclib.net/api/search",
                        params={"q": f"{artist} {title}"}, timeout=20).json()
        best = next((x for x in arr if x.get("syncedLyrics")), None) or (arr[0] if arr else None)
        if best:
            lyrics = best.get("syncedLyrics") or best.get("plainLyrics")
            if lyrics:
                return {"synced": bool(best.get("syncedLyrics")), "source": "lrclib", "lyrics": lyrics}
    except Exception:
        pass
    return None


@app.get("/api/lyrics")
def lyrics(artist: str = Query(...), title: str = Query(...)):
    res = _lyrics_from_lyrica(artist, title) or _lyrics_from_lrclib(artist, title)
    if res:
        return {"success": True, **res}
    raise HTTPException(404, "Lirik tidak ditemukan")


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# PWA: service worker harus di root agar scope-nya '/' (mengontrol seluruh app).
@app.get("/sw.js")
def service_worker():
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")
