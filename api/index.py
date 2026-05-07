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


def fix_url(url: str) -> str:
    """Bersihkan URL — unescape slash, tambah domain jika tidak ada"""
    if not url:
        return url
    url = url.replace("\\/", "/")
    if url.startswith("/"):
        url = BASE_DOMAIN + url
    return url


def get_video_src(slug: str, ep: int):
    key = f"{slug}_{ep}"
    now = time.time()

    if key in video_cache:
        cached = video_cache[key]
        if now - cached["time"] < VIDEO_CACHE_TTL:
            return cached["url"]

    warm_session(slug, ep)

    refresh_url = f"{BASE_DOMAIN}/detail/watch/{slug}/{ep}/refresh-source?lang=id-ID&force=1"

    for attempt in range(5):
        try:
            resp = session.get(refresh_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()

                # PRIORITAS 1: direct_play_url — URL CDN langsung, tidak butuh proxy
                direct_url = data.get("direct_play_url")
                if direct_url and direct_url.startswith("http"):
                    video_cache[key] = {"url": direct_url, "time": now}
                    return direct_url

                # PRIORITAS 2: play_url — tambah domain jika relatif
                play_url = data.get("play_url") or data.get("url") or data.get("src")
                if play_url:
                    play_url = fix_url(play_url)
                    video_cache[key] = {"url": play_url, "time": now}
                    return play_url

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
# PLAY — redirect langsung ke stream (bisa dibuka di browser)
# =========================
from fastapi.responses import RedirectResponse, HTMLResponse
from urllib.parse import quote

@app.get("/play")
async def play(slug: str, ep: int = 1):
    """
    Akses langsung dari browser — redirect ke stream.
    Contoh: /play?slug=drama-slug&ep=1
    """
    # Langsung redirect ke /stream?slug=&ep= — tidak perlu URL manual
    stream_url = f"/stream?slug={slug}&ep={ep}"
    return RedirectResponse(url=stream_url, status_code=302)


# =========================
# PLAYER — halaman HTML video player langsung di browser
# =========================
@app.get("/player")
async def player(slug: str, ep: int = 1):
    """
    Halaman video player HTML — bisa dibuka langsung di browser.
    Contoh: /player?slug=drama-slug&ep=1
    """
    # Gunakan /stream?slug=&ep= langsung — tidak perlu generate URL manual
    stream_url = f"/stream?slug={slug}&ep={ep}"

    # Ambil detail drama untuk judul
    detail_data = scrape_detail(slug)
    title = detail_data.get("title", slug)
    total_ep = detail_data.get("total_episode", 1)

    # Generate tombol episode
    ep_buttons = ""
    for i in range(1, min(total_ep + 1, 51)):  # max 50 tombol
        active = "background:#e50914;color:white;" if i == ep else ""
        ep_buttons += f'<button onclick="changeEp({i})" style="margin:3px;padding:6px 12px;border:none;border-radius:4px;cursor:pointer;background:#333;color:white;{active}">{i}</button>'

    html = f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} - Episode {ep}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: #141414; color: white; font-family: Arial, sans-serif; }}
    .header {{ padding: 16px 20px; background: #1a1a1a; border-bottom: 1px solid #333; }}
    .header h1 {{ font-size: 18px; color: #e50914; }}
    .header p {{ font-size: 13px; color: #aaa; margin-top: 4px; }}
    .player-wrap {{ width: 100%; background: black; }}
    video {{ width: 100%; max-height: 75vh; display: block; }}
    .episodes {{ padding: 16px 20px; }}
    .episodes h3 {{ margin-bottom: 10px; font-size: 14px; color: #aaa; }}
    .ep-grid {{ display: flex; flex-wrap: wrap; gap: 4px; }}
    .loading {{ text-align: center; padding: 40px; color: #aaa; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>{title}</h1>
    <p>Episode {ep} dari {total_ep}</p>
  </div>

  <div class="player-wrap">
    <video id="vid" controls autoplay preload="auto">
      <source src="{stream_url}" type="video/mp4">
      Browser tidak support video tag.
    </video>
  </div>

  <div class="episodes">
    <h3>Pilih Episode:</h3>
    <div class="ep-grid">
      {ep_buttons}
    </div>
  </div>

  <script>
    function changeEp(num) {{
      window.location.href = "/player?slug={slug}&ep=" + num;
    }}

    // Error handler — coba reload jika gagal
    const vid = document.getElementById("vid");
    vid.addEventListener("error", function() {{
      console.error("Video error, retrying...");
      setTimeout(() => {{ vid.load(); vid.play(); }}, 2000);
    }});
  </script>
</body>
</html>"""

    return HTMLResponse(content=html)


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
# DEBUG — cek status video URL
# =========================
@app.get("/debug")
async def debug(slug: str, ep: int = 1):
    """
    Debug endpoint — tampilkan semua info tentang video URL.
    Contoh: /debug?slug=drama-slug&ep=1
    """
    result = {"slug": slug, "ep": ep}

    # Step 1: warm session
    try:
        warm_url = f"{BASE_DOMAIN}/detail/watch/{slug}/{ep}?lang=id-ID"
        r = session.get(warm_url, timeout=10)
        result["warm_status"] = r.status_code
        result["cookies"] = list(session.cookies.keys())
    except Exception as e:
        result["warm_error"] = str(e)

    # Step 2: refresh-source
    try:
        refresh_url = f"{BASE_DOMAIN}/detail/watch/{slug}/{ep}/refresh-source?lang=id-ID&force=1"
        r2 = session.get(refresh_url, timeout=10)
        result["refresh_status"] = r2.status_code
        result["refresh_raw"] = r2.text[:500]
        if r2.status_code == 200:
            try:
                result["refresh_json"] = r2.json()
            except:
                result["refresh_json"] = "bukan JSON"
    except Exception as e:
        result["refresh_error"] = str(e)

    # Step 3: test akses video URL
    video_url = get_video_src(slug, ep)
    result["video_url"] = video_url

    if video_url:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                head = await client.head(video_url, headers=STREAM_HEADERS)
                result["video_status"] = head.status_code
                result["video_content_type"] = head.headers.get("content-type")
                result["video_final_url"] = str(head.url)
        except Exception as e:
            result["video_head_error"] = str(e)

    return result


# =========================
# STREAM — support /stream/proxy URL
# =========================
@app.get("/stream")
async def stream(request: Request, slug: str = None, ep: int = None):
    """
    Stream video proxy.
    Cara termudah: /stream?slug=drama-slug&ep=1
    """
    decoded_url = None
    error_detail = {}

    # =========================
    # MODE 1: slug+ep → generate URL fresh (DIREKOMENDASIKAN)
    # =========================
    has_url_param = "url=" in str(request.url.query)

    if slug and ep and not has_url_param:
        try:
            warm_session(slug, ep)
            decoded_url = get_video_src(slug, ep)
        except Exception as e:
            return JSONResponse(status_code=500, content={
                "error": f"Gagal get_video_src: {str(e)}",
                "slug": slug,
                "ep": ep,
                "hint": "Cek /debug?slug={slug}&ep={ep} untuk detail"
            })

        if not decoded_url:
            return JSONResponse(status_code=404, content={
                "error": "Video URL kosong — refresh-source tidak mengembalikan URL",
                "slug": slug,
                "ep": ep,
                "hint": f"Cek /debug?slug={slug}&ep={ep} untuk detail lengkap"
            })

    else:
        # =========================
        # MODE 2: URL eksplisit dari query string
        # =========================
        raw_query = str(request.url.query)
        idx = raw_query.find("url=")

        if idx == -1:
            return JSONResponse(status_code=400, content={
                "error": "Parameter 'url' tidak ditemukan",
                "hint": "Gunakan /stream?slug=SLUG&ep=1"
            })

        url_raw = raw_query[idx + 4:]

        for suffix in ["&slug=", "&ep="]:
            pos = url_raw.rfind(suffix)
            if pos != -1:
                url_raw = url_raw[:pos]

        decoded_url = unquote(unquote(url_raw))

        if decoded_url.startswith("/stream/proxy") or decoded_url.startswith("stream/proxy"):
            decoded_url = BASE_DOMAIN + "/" + decoded_url.lstrip("/")

        if not decoded_url.startswith("http"):
            return JSONResponse(status_code=400, content={
                "error": f"URL tidak valid: {decoded_url[:120]}",
                "hint": "Gunakan /stream?slug=SLUG&ep=1"
            })

        if "/stream/proxy" in decoded_url and slug and ep:
            warm_session(slug, ep)

    # =========================
    # STREAM VIDEO
    # =========================
    is_proxy_url = "/stream/proxy" in decoded_url
    cookies = dict(session.cookies)
    headers = dict(STREAM_HEADERS)

    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    # Ikuti redirect manual untuk proxy URL
    if is_proxy_url:
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=15) as check:
                head_resp = await check.head(decoded_url, headers=headers, cookies=cookies)
                if head_resp.status_code in (301, 302, 307, 308):
                    location = head_resp.headers.get("location")
                    if location:
                        decoded_url = location
        except Exception as e:
            pass  # lanjut dengan URL asli

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, connect=15.0),
            cookies=cookies
        ) as client:
            async with client.stream("GET", decoded_url, headers=headers) as r:

                if r.status_code in (403, 404, 401):
                    # Coba refresh URL jika ada slug+ep
                    if slug and ep:
                        new_url = get_video_src(slug, int(ep))
                        if new_url and new_url != decoded_url:
                            async with client.stream("GET", new_url, headers=headers) as r2:
                                if r2.status_code in (200, 206):
                                    resp_h = {
                                        "Content-Type": r2.headers.get("content-type", "video/mp4"),
                                        "Accept-Ranges": "bytes",
                                        "Access-Control-Allow-Origin": "*",
                                        "Cache-Control": "no-cache",
                                    }
                                    if "content-length" in r2.headers:
                                        resp_h["Content-Length"] = r2.headers["content-length"]
                                    if "content-range" in r2.headers:
                                        resp_h["Content-Range"] = r2.headers["content-range"]
                                    return StreamingResponse(
                                        r2.aiter_bytes(chunk_size=1024 * 512),
                                        status_code=r2.status_code,
                                        headers=resp_h,
                                    )

                    return JSONResponse(
                        status_code=r.status_code,
                        content={
                            "error": f"Stream server returned {r.status_code}",
                            "video_url": decoded_url[:100] + "...",
                            "hint": f"Cek /debug?slug={slug}&ep={ep}"
                        }
                    )

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
        return JSONResponse(status_code=504, content={"error": "Stream timeout"})
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "video_url": decoded_url[:100] if decoded_url else None,
            "hint": f"Cek /debug?slug={slug}&ep={ep} untuk detail"
        })

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
