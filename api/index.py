from fastapi import FastAPI, Query
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import StreamingResponse, JSONResponse
from mangum import Mangum
import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse
from urllib.parse import unquote
import time
import httpx

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

handler = Mangum(app)

BASE_DOMAIN = "https://narto-drama.com"
ALL_DRAMAS = []
GENRE_INDEX = {}
LAST_UPDATE = 0
CACHE_TTL = 60 * 30  # 30 menit

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE_DOMAIN,
    "Connection": "keep-alive",
}

STREAM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": BASE_DOMAIN + "/",
    "Origin": BASE_DOMAIN,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
}

# =========================
# SESSION GLOBAL (simpan cookies)
# =========================
session = requests.Session()
session.headers.update(HEADERS)


def warm_session(slug: str, ep: int):
    """Buka halaman episode dulu untuk dapat cookies yang valid"""
    try:
        warm_url = f"{BASE_DOMAIN}/detail/watch/{slug}/{ep}?lang=id-ID"
        session.get(warm_url, timeout=10)
    except Exception as e:
        print(f"[warm_session] failed: {e}")


# =========================
# GENRE
# =========================
def normalize_genres(tags, title):
    genres = set()

    tag_map = {
        "romantis": "Romance", "romansa": "Romance", "cinta": "Romance",
        "love": "Romance", "nikah": "Romance",
        "ceo": "Drama", "kantoran": "Drama", "kehidupan": "Drama", "modern": "Drama",
        "komedi": "Comedy", "lucu": "Comedy", "kocak": "Comedy",
        "aksi": "Action", "dewa perang": "Action", "perang": "Action", "pertarungan": "Action",
        "fantasi": "Fantasy", "sistem": "Fantasy", "reinkarnasi": "Fantasy",
        "time travel": "Fantasy", "kelahiran kembali": "Fantasy",
        "kekuatan super": "Fantasy", "transmigrasi": "Fantasy",
        "keluarga": "Family", "anak": "Family", "ayah": "Family", "ibu": "Family",
        "bisnis": "Business", "miliarder": "Business", "konglomerat": "Business",
        "kaya": "Business", "direktur": "Business",
        "mafia": "Crime", "kriminal": "Crime", "penjara": "Crime", "pembunuh": "Crime",
        "misteri": "Mystery", "rahasia": "Mystery", "detektif": "Mystery",
        "kiamat": "Sci-Fi", "apokalips": "Sci-Fi", "monster": "Sci-Fi", "alien": "Sci-Fi"
    }

    for tag in tags:
        t = tag.lower()
        for key, val in tag_map.items():
            if key in t:
                genres.add(val)

    t = title.lower()
    if "cinta" in t or "nikah" in t:
        genres.add("Romance")
    if "bos" in t or "ceo" in t:
        genres.add("Drama")
        genres.add("Business")
    if "balas" in t or "dendam" in t:
        genres.add("Action")
    if "sistem" in t or "reinkarnasi" in t:
        genres.add("Fantasy")
    if "keluarga" in t or "anak" in t:
        genres.add("Family")
    if "mafia" in t or "penjara" in t:
        genres.add("Crime")
    if "rahasia" in t:
        genres.add("Mystery")
    if "kiamat" in t:
        genres.add("Sci-Fi")

    if not genres:
        genres.add("Drama")

    return list(genres)


VALID_GENRES = {
    "Romance", "Drama", "Comedy", "Action", "Fantasy",
    "Family", "Business", "Crime", "Mystery", "Sci-Fi"
}


def clean_genres(genres):
    return [g for g in genres if g in VALID_GENRES]


def build_index(max_page=20, delay=0.5):
    global ALL_DRAMAS, GENRE_INDEX, LAST_UPDATE

    ALL_DRAMAS = []
    GENRE_INDEX = {}

    for page in range(1, max_page + 1):
        url = f"{BASE_DOMAIN}/?lang=id-ID&page={page}"
        data = scrape_list(url)

        if "items" not in data:
            break

        for item in data["items"]:
            genres = normalize_genres(item["tags"], item["title"])
            genres = clean_genres(genres)
            item["genres"] = genres
            ALL_DRAMAS.append(item)

            for g in genres:
                if g not in GENRE_INDEX:
                    GENRE_INDEX[g] = []
                GENRE_INDEX[g].append(item)

        if not data.get("has_next"):
            break

        time.sleep(delay)

    LAST_UPDATE = time.time()


def ensure_cache():
    global LAST_UPDATE
    if time.time() - LAST_UPDATE > CACHE_TTL or not ALL_DRAMAS:
        build_index()


# =========================
# UTIL
# =========================
def extract_slug(url: str) -> str:
    try:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        return path.split("/")[-1] if path else ""
    except:
        return ""


def clean_url(url: str):
    return url.replace("\\/", "/").replace("\\u0026", "&")


# =========================
# SCRAPE LIST
# =========================
def scrape_list(url):
    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        items = []

        for card in soup.find_all("article", class_="card"):
            title_tag = card.find("h3", class_="title")
            title = title_tag.get_text(strip=True) if title_tag else ""

            link_tag = card.find("a", class_="card-link-overlay")
            href = link_tag.get("href") if link_tag else None

            if href and not href.startswith("http"):
                href = BASE_DOMAIN + href

            img_tag = card.find("img", class_="poster")
            thumbnail = img_tag.get("src") if img_tag else None
            if thumbnail and thumbnail.startswith("/"):
                thumbnail = BASE_DOMAIN + thumbnail

            tags = [t.get_text(strip=True) for t in card.find_all("a", class_="movie-tag")]

            if title and href:
                items.append({
                    "title": title,
                    "href": href.split("?")[0],
                    "slug": extract_slug(href),
                    "thumbnail": thumbnail,
                    "tags": tags
                })

        has_next = False
        pager = soup.find("div", class_="pager")
        if pager:
            next_btn = pager.find("a", class_="pager-link", string=lambda x: x and "Next" in x)
            if next_btn:
                has_next = True

        return {"items": items, "has_next": has_next}

    except Exception as e:
        return {"error": str(e)}


# =========================
# DETAIL
# =========================
def scrape_detail(slug: str):
    try:
        url = f"{BASE_DOMAIN}/detail/watch/{slug}?lang=id-ID&from=home"
        resp = session.get(url, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.find("h1", class_="movie-title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        sub_tag = soup.find("p", class_="movie-sub")
        episode_text = sub_tag.get_text(" ", strip=True) if sub_tag else ""

        total_episode = 0
        match = re.search(r"(\d+)\s*Episode", episode_text)
        if match:
            total_episode = int(match.group(1))

        desc_tag = soup.find("div", class_="movie-desc")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        tags = []
        for tag in soup.find_all("a", class_="movie-tag-pill"):
            tags.append(tag.get_text(strip=True))

        img_tag = soup.find("img", class_="poster")
        if not img_tag:
            img_tag = soup.find("img")

        thumbnail = img_tag.get("src") if img_tag else None
        if thumbnail and thumbnail.startswith("/"):
            thumbnail = BASE_DOMAIN + thumbnail

        return {
            "title": title,
            "thumbnail": thumbnail,
            "description": description,
            "tags": tags,
            "total_episode": total_episode,
            "episode_raw": episode_text
        }

    except Exception as e:
        return {"error": str(e)}


# =========================
# EPISODES
# =========================
def get_total_episodes(slug: str):
    url = f"{BASE_DOMAIN}/{slug}"
    resp = session.get(url, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")
    episodes = soup.find_all("a", class_="episode-item")
    return len(episodes)


# =========================
# VIDEO
# =========================
def get_all_video_links(slug: str):
    url = f"{BASE_DOMAIN}/detail/watch/{slug}/1?lang=id-ID"
    resp = session.get(url, timeout=10)

    if resp.status_code != 200:
        return []

    html = resp.text
    match = re.search(r'episodeItemsRaw\s*=\s*(\[[\s\S]*?\])', html)
    if not match:
        return []

    episodes = json.loads(match.group(1))
    result = []

    for item in episodes:
        play_url = item.get("play_url")
        if play_url:
            play_url = play_url.replace("\\/", "/")
        result.append({
            "episode": int(item.get("number", 0)),
            "video_url": play_url
        })

    return result


video_cache = {}
VIDEO_CACHE_TTL = 60 * 5  # 5 menit


def get_video_src(slug: str, ep: int):
    key = f"{slug}_{ep}"
    now = time.time()

    # Cek cache
    if key in video_cache:
        cached = video_cache[key]
        if now - cached["time"] < VIDEO_CACHE_TTL:
            return cached["url"]

    # 🔥 Warm session — buka halaman dulu agar cookies valid
    warm_session(slug, ep)

    refresh_url = f"{BASE_DOMAIN}/detail/watch/{slug}/{ep}/refresh-source?lang=id-ID&force=1"

    for attempt in range(5):
        try:
            resp = session.get(refresh_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                url = data.get("play_url") or data.get("url") or data.get("src")
                if url:
                    url = url.replace("\\/", "/")
                    video_cache[key] = {"url": url, "time": now}
                    return url
        except Exception as e:
            print(f"[get_video_src] attempt {attempt + 1} failed: {e}")

        time.sleep(1.5)

    return None


# =========================
# ROUTES
# =========================

@app.get("/")
def home():
    return {"status": "API Running 🚀"}


@app.get("/list")
def list_api(page: int = 1):
    url = f"{BASE_DOMAIN}/?lang=id-ID&page={page}"
    return {"page": page, "data": scrape_list(url)}


@app.get("/list-all")
def list_all(max_page: int = 5, delay: float = 1):
    all_items = []

    for page in range(1, max_page + 1):
        url = f"{BASE_DOMAIN}/?lang=id-ID&page={page}"
        data = scrape_list(url)

        if "items" in data:
            all_items.extend(data["items"])

        if not data.get("has_next"):
            break

        time.sleep(delay)

    return {"total": len(all_items), "data": all_items}


@app.get("/search")
def search(q: str):
    url = f"{BASE_DOMAIN}/search?lang=id-ID&q={q}"
    return scrape_list(url)


@app.get("/detail")
def detail(slug: str):
    return {"slug": slug, "data": scrape_detail(slug)}


@app.get("/episodes")
def episodes(slug: str):
    return {"slug": slug, "total_episode": get_total_episodes(slug)}


@app.get("/videos")
def videos(slug: str):
    return {"slug": slug, "data": get_all_video_links(slug)}


@app.get("/video")
def video(slug: str, ep: int = 1):
    return {
        "slug": slug,
        "episode": ep,
        "video_url": get_video_src(slug, ep)
    }


# =========================
# RESOLVE — debug URL proxy
# =========================
@app.get("/resolve")
async def resolve_url(url: str):
    """
    Resolve /stream/proxy URL untuk debug.
    Mengembalikan status, final URL, redirect, dan headers dari server.
    Contoh: /resolve?url=https://narto-drama.com/stream/proxy?...
    """
    decoded_url = unquote(unquote(url))
    cookies = dict(session.cookies)

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
            resp = await client.get(decoded_url, headers=STREAM_HEADERS, cookies=cookies)

            return {
                "status_code": resp.status_code,
                "final_url": str(resp.url),
                "redirect_to": resp.headers.get("location"),
                "content_type": resp.headers.get("content-type"),
                "all_headers": dict(resp.headers)
            }
    except Exception as e:
        return {"error": str(e)}


# =========================
# STREAM — support /stream/proxy URL
# =========================
@app.get("/stream")
async def stream(request: Request, slug: str = None, ep: int = None):
    """
    Stream video proxy.

    Untuk URL biasa:
      /stream?url=https%3A%2F%2F...video.mp4   ← URL harus di-encodeURIComponent

    Untuk URL /stream/proxy, kirim juga slug & ep:
      /stream?url=https%3A%2F%2Fnarto-drama.com%2Fstream%2Fproxy%3F...&slug=drama-slug&ep=1

    PENTING: parameter `url` HARUS di-encodeURIComponent dari sisi frontend/client.
    """
    # =========================
    # 🔥 Ambil raw query string untuk reconstruct URL yang benar
    # =========================
    raw_query = request.url.query  # full query string mentah

    # Ambil nilai `url=` dari raw query string
    # Ini lebih aman daripada FastAPI param parsing karena URL bisa mengandung & yang tidak di-encode
    url_param = None
    for part in raw_query.split("&"):
        if part.startswith("url="):
            # Ambil SEMUA sisanya setelah "url=" sebagai URL mentah
            url_param = part[4:]
            break

    if not url_param:
        return JSONResponse(status_code=400, content={"error": "Parameter 'url' tidak ditemukan"})

    # Decode URL (handle double-encode juga)
    decoded_url = unquote(unquote(url_param))

    # =========================
    # 🔥 Auto-fix: jika URL tidak punya domain (terpotong), tambahkan BASE_DOMAIN
    # =========================
    if decoded_url.startswith("/stream/proxy") or decoded_url.startswith("stream/proxy"):
        decoded_url = BASE_DOMAIN + "/" + decoded_url.lstrip("/")

    # Validasi URL
    if not decoded_url.startswith("http"):
        return JSONResponse(
            status_code=400,
            content={
                "error": f"URL tidak valid: {decoded_url[:100]}",
                "hint": "Pastikan parameter 'url' di-encodeURIComponent terlebih dahulu. Contoh: /stream?url=https%3A%2F%2Fnarto-drama.com%2Fstream%2Fproxy%3F..."
            }
        )

    # =========================
    # 🔥 Deteksi /stream/proxy URL
    # =========================
    is_proxy_url = "/stream/proxy" in decoded_url

    # Warm session jika proxy URL dan slug/ep tersedia
    if is_proxy_url and slug and ep:
        warm_session(slug, ep)

    cookies = dict(session.cookies)
    headers = dict(STREAM_HEADERS)

    # Teruskan Range header jika ada (untuk seek video)
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    # =========================
    # 🔥 Untuk /stream/proxy: ikuti redirect manual dulu
    # =========================
    if is_proxy_url:
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=15) as check:
                head_resp = await check.head(decoded_url, headers=headers, cookies=cookies)

                # Jika server redirect → pakai URL tujuan redirect
                if head_resp.status_code in (301, 302, 307, 308):
                    location = head_resp.headers.get("location")
                    if location:
                        decoded_url = location
                        print(f"[stream] Redirected to: {decoded_url}")
        except Exception as e:
            print(f"[stream] HEAD check failed: {e}")

    # =========================
    # STREAM VIDEO
    # =========================
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, connect=15.0),
            cookies=cookies
        ) as client:
            async with client.stream("GET", decoded_url, headers=headers) as r:

                # 🔥 Jika masih 403/404 → coba auto-refresh URL via slug & ep
                if r.status_code in (403, 404, 401):
                    # Jika ada slug & ep, generate URL baru otomatis
                    if slug and ep:
                        new_url = get_video_src(slug, int(ep))
                        if new_url and new_url != decoded_url:
                            # Retry dengan URL baru
                            async with client.stream("GET", new_url, headers=headers) as r2:
                                if r2.status_code == 200 or r2.status_code == 206:
                                    response_headers = {
                                        "Content-Type": r2.headers.get("content-type", "video/mp4"),
                                        "Accept-Ranges": "bytes",
                                        "Access-Control-Allow-Origin": "*",
                                        "Cache-Control": "no-cache",
                                    }
                                    if "content-length" in r2.headers:
                                        response_headers["Content-Length"] = r2.headers["content-length"]
                                    if "content-range" in r2.headers:
                                        response_headers["Content-Range"] = r2.headers["content-range"]

                                    return StreamingResponse(
                                        r2.aiter_bytes(chunk_size=1024 * 512),
                                        status_code=r2.status_code,
                                        headers=response_headers,
                                    )

                    # Tidak bisa di-recover
                    return JSONResponse(
                        status_code=r.status_code,
                        content={
                            "error": f"Stream server returned {r.status_code}",
                            "url": decoded_url,
                            "hint": "URL expired atau IP tidak dikenali. Kirim parameter slug & ep untuk auto-refresh. Contoh: /stream?url=...&slug=drama-slug&ep=1"
                        }
                    )

                # =========================
                # Susun response headers
                # =========================
                response_headers = {
                    "Content-Type": r.headers.get("content-type", "video/mp4"),
                    "Accept-Ranges": "bytes",
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "no-cache",
                }

                if "content-length" in r.headers:
                    response_headers["Content-Length"] = r.headers["content-length"]

                if "content-range" in r.headers:
                    response_headers["Content-Range"] = r.headers["content-range"]

                return StreamingResponse(
                    r.aiter_bytes(chunk_size=1024 * 512),
                    status_code=r.status_code,
                    headers=response_headers,
                )

    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": "Stream timeout — server tidak merespon"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# =========================
# GENRES
# =========================
@app.get("/genres")
def get_genres():
    ensure_cache()
    return {"genres": list(GENRE_INDEX.keys())}


@app.get("/genre/{genre}")
def get_by_genre(genre: str, page: int = 1, limit: int = 20):
    ensure_cache()

    data = GENRE_INDEX.get(genre, [])
    start = (page - 1) * limit
    end = start + limit

    return {
        "genre": genre,
        "total": len(data),
        "page": page,
        "data": {
            "items": data[start:end]
        }
    }


@app.get("/filter")
def filter_api(
    genre: str = None,
    keyword: str = None,
    page: int = 1,
    limit: int = 20
):
    ensure_cache()

    data = ALL_DRAMAS

    if genre:
        data = GENRE_INDEX.get(genre, [])

    if keyword:
        keyword = keyword.lower()
        data = [d for d in data if keyword in d["title"].lower()]

    start = (page - 1) * limit
    end = start + limit

    return {
        "total": len(data),
        "page": page,
        "results": data[start:end]
    }
