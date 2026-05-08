from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from mangum import Mangum
import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse, parse_qs, urlencode, unquote
import time
import httpx
import asyncio

# =========================
# APP INIT
# =========================
app = FastAPI()
__all__ = ["app"]

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_DOMAIN
}

STREAM_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": BASE_DOMAIN,
    "Origin": BASE_DOMAIN
}

video_cache = {}
VIDEO_CACHE_TTL = 0

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
    if "cinta" in t or "nikah" in t: genres.add("Romance")
    if "bos" in t or "ceo" in t: genres.add("Drama"); genres.add("Business")
    if "balas" in t or "dendam" in t: genres.add("Action")
    if "sistem" in t or "reinkarnasi" in t: genres.add("Fantasy")
    if "keluarga" in t or "anak" in t: genres.add("Family")
    if "mafia" in t or "penjara" in t: genres.add("Crime")
    if "rahasia" in t: genres.add("Mystery")
    if "kiamat" in t: genres.add("Sci-Fi")

    if not genres:
        genres.add("Drama")

    return list(genres)

VALID_GENRES = {
    "Romance", "Drama", "Comedy", "Action", "Fantasy",
    "Family", "Business", "Crime", "Mystery", "Sci-Fi"
}

def clean_genres(genres):
    return [g for g in genres if g in VALID_GENRES]

# =========================
# CACHE / INDEX
# =========================
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
        resp = requests.get(url, headers=HEADERS, timeout=10)
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
# SCRAPE SEARCH (JSON)
# =========================
async def scrape_search_results(q: str):
    url = f"{BASE_DOMAIN}/search"
    params = {'q': q, 'lang': 'id-ID'}

    SEARCH_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_DOMAIN}/",
        "Accept": "application/json, text/javascript, */*; q=0.01"
    }

    async with httpx.AsyncClient(headers=SEARCH_HEADERS, timeout=15.0) as client:
        try:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    raw_items = data.get("items", [])
                    results = []

                    for item in raw_items:
                        original_url = item.get("url", "")
                        poster = item.get("poster_url", "")
                        if poster and poster.startswith("/"):
                            poster = f"{BASE_DOMAIN}{poster}"

                        results.append({
                            "title": item.get("title", ""),
                            "href": original_url,
                            "slug": extract_slug(original_url),
                            "thumbnail": poster,
                            "description": item.get("description", ""),
                            "tags": item.get("tags", [])
                        })

                    return {"status": "success", "count": len(results), "items": results}
                except Exception:
                    return {"error": "Format JSON tidak valid", "raw": resp.text[:500]}

            return {"error": f"Server status {resp.status_code}", "items": []}
        except Exception as e:
            return {"error": str(e), "items": []}

# =========================
# SCRAPE SEARCH (HTML FULL)
# =========================
async def scrape_full_search(q: str, page: int = 1):
    url = f"{BASE_DOMAIN}/search"
    params = {'q': q, 'lang': 'id-ID', 'page': page}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Referer": f"{BASE_DOMAIN}/"
    }

    async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return {"error": f"Site returned {resp.status_code}", "items": []}

            soup = BeautifulSoup(resp.text, "html.parser")
            items = []

            for card in soup.find_all("article", class_="card"):
                title_tag = card.find("h3", class_="title")
                link_tag = card.find("a", class_="card-link-overlay")
                img_tag = card.find("img", class_="poster")

                if title_tag and link_tag:
                    raw_href = link_tag.get("href", "")
                    title = title_tag.get_text(strip=True)

                    if "/search/import" in raw_href:
                        parsed = urlparse(raw_href)
                        slug = f"import?{parsed.query}"
                        item_type = "import"
                        full_url = f"{BASE_DOMAIN}{raw_href}" if raw_href.startswith("/") else raw_href
                    else:
                        clean_href = raw_href.split("?")[0]
                        slug = extract_slug(clean_href)
                        item_type = "local"
                        full_url = f"{BASE_DOMAIN}{clean_href}" if clean_href.startswith("/") else clean_href

                    thumb = img_tag.get("src") if img_tag else None
                    if thumb and thumb.startswith("/"):
                        thumb = f"{BASE_DOMAIN}{thumb}"

                    items.append({
                        "title": title,
                        "href": full_url,
                        "slug": slug,
                        "type": item_type,
                        "thumbnail": thumb,
                        "status": card.find("div", class_="card-ep").get_text(strip=True) if card.find("div", class_="card-ep") else "",
                        "tags": [t.get_text(strip=True) for t in card.find_all("a", class_="movie-tag")]
                    })

            has_next = False
            pager = soup.find("div", class_="pager")
            if pager:
                next_btn = pager.find("a", class_="pager-link", string=lambda x: x and "Next" in x)
                has_next = True if next_btn else False

            return {
                "query": q,
                "current_page": page,
                "has_next": has_next,
                "count": len(items),
                "items": items
            }
        except Exception as e:
            return {"error": str(e), "items": []}

# =========================
# RESOLVE IMPORT (INTERNAL)
# =========================
async def resolve_import_internal(slug: str):
    decoded_slug = unquote(slug)

    if not decoded_slug.startswith("import?"):
        return {"final_slug": decoded_slug}

    query_part = decoded_slug[len("import?"):]
    import_url = f"{BASE_DOMAIN}/search/import?{query_part}"

    for attempt in range(10):
        try:
            resp = requests.get(import_url, headers=HEADERS, timeout=15, allow_redirects=True)
            final_url = str(resp.url)

            print(f"[resolve-import] Attempt {attempt+1}: {final_url}")

            # Sukses: sudah redirect ke detail
            if "/detail/watch/" in final_url:
                return {"final_slug": extract_slug(final_url.split("?")[0])}

            soup = BeautifulSoup(resp.text, "html.parser")

            # Cek meta refresh
            meta_refresh = soup.find("meta", attrs={"http-equiv": "refresh"})
            if meta_refresh:
                content = meta_refresh.get("content", "")
                url_match = re.search(r'url=(.+)', content, re.IGNORECASE)
                if url_match:
                    redirect_url = url_match.group(1).strip()
                    if not redirect_url.startswith("http"):
                        redirect_url = BASE_DOMAIN + redirect_url
                    if "/detail/watch/" in redirect_url:
                        return {"final_slug": extract_slug(redirect_url.split("?")[0])}

            # Cek JS redirect
            for script in soup.find_all("script"):
                text = script.get_text()
                match = re.search(r'(?:window\.location|location\.href)\s*=\s*["\']([^"\']+)["\']', text)
                if match and "/detail/watch/" in match.group(1):
                    return {"final_slug": extract_slug(match.group(1).split("?")[0])}

            # Cek link langsung
            detail_link = soup.find("a", href=re.compile(r"/detail/watch/"))
            if detail_link:
                return {"final_slug": extract_slug(detail_link["href"].split("?")[0])}

            print(f"[resolve-import] Belum selesai, retry {attempt+1}/10...")
            time.sleep(2)

        except Exception as e:
            print(f"[resolve-import] Error attempt {attempt+1}: {e}")
            time.sleep(2)

    return {"final_slug": None}

# =========================
# SCRAPE DETAIL
# =========================
def scrape_detail(slug: str):
    try:
        url = f"{BASE_DOMAIN}/detail/watch/{slug}?lang=id-ID&from=home"
        print(f"[scrape_detail] Fetching: {url}")

        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()

        final_url = str(resp.url)
        final_slug = extract_slug(final_url.split("?")[0])

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

        tags = [tag.get_text(strip=True) for tag in soup.find_all("a", class_="movie-tag-pill")]

        img_tag = soup.find("img", class_="poster") or soup.find("img")
        thumbnail = img_tag.get("src") if img_tag else None
        if thumbnail and thumbnail.startswith("/"):
            thumbnail = BASE_DOMAIN + thumbnail

        return {
            "title": title,
            "thumbnail": thumbnail,
            "description": description,
            "tags": tags,
            "total_episode": total_episode,
            "episode_raw": episode_text,
            "final_slug": final_slug,
        }

    except Exception as e:
        return {"error": str(e)}

# =========================
# EPISODES
# =========================
def get_total_episodes(slug: str):
    url = f"{BASE_DOMAIN}/detail/watch/{slug}?lang=id-ID"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")
    episodes = soup.find_all("a", class_="episode-item")
    return len(episodes)

# =========================
# VIDEO
# =========================
def get_all_video_links(slug: str):
    url = f"{BASE_DOMAIN}/detail/watch/{slug}/1?lang=id-ID"
    resp = requests.get(url, headers=HEADERS, timeout=10)

    if resp.status_code != 200:
        return []

    match = re.search(r'episodeItemsRaw\s*=\s*(\[[\s\S]*?\])', resp.text)
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

def get_video_src(slug: str, ep: int):
    key = f"{slug}_{ep}"
    now = time.time()

    if key in video_cache:
        cached = video_cache[key]
        if now - cached["time"] < VIDEO_CACHE_TTL:
            return cached["url"]

    refresh_url = f"{BASE_DOMAIN}/detail/watch/{slug}/{ep}/refresh-source?lang=id-ID&force=1"

    for _ in range(5):
        try:
            resp = requests.get(refresh_url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                url = data.get("play_url")

                if url:
                    if "/stream/proxy?ah=narto-drama.com" in url:
                        url = data.get("direct_play_url", url)

                    video_cache[key] = {"url": url, "time": now}
                    return url
        except Exception:
            pass
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
async def search(q: str):
    return await scrape_search_results(q)


@app.get("/search-full")
async def search_full(q: str, page: int = 1):
    return await scrape_full_search(q, page)


@app.get("/resolve-import")
async def resolve_import_endpoint(slug: str = Query(...)):
    decoded_slug = unquote(slug)

    if not decoded_slug.startswith("import?"):
        return {"error": "Bukan import slug", "final_slug": decoded_slug}

    result = await resolve_import_internal(decoded_slug)

    if not result.get("final_slug"):
        return {
            "status": "failed",
            "message": "Import tidak selesai setelah beberapa percobaan",
            "final_slug": None
        }

    return {
        "status": "success",
        "final_slug": result["final_slug"]
    }


@app.get("/detail")
async def detail(request: Request):
    # 🔥 Ambil raw query agar slug import tidak terpotong
    raw_query = str(request.url.query)

    if raw_query.startswith("slug="):
        full_slug = unquote(raw_query[len("slug="):])
    else:
        full_slug = request.query_params.get("slug", "")

    # Import slug → resolve dulu
    if full_slug.startswith("import?") or full_slug == "import":
        resolve_result = await resolve_import_internal(full_slug)

        if not resolve_result.get("final_slug"):
            return {
                "slug": full_slug,
                "final_slug": None,
                "was_imported": True,
                "import_status": "failed",
                "data": {"error": "Gagal import drama"}
            }

        final_slug = resolve_result["final_slug"]
        data = scrape_detail(final_slug)

        return {
            "slug": full_slug,
            "final_slug": final_slug,
            "was_imported": True,
            "import_status": "success",
            "data": data
        }

    # Slug biasa
    data = scrape_detail(full_slug)
    return {
        "slug": full_slug,
        "final_slug": data.get("final_slug", full_slug),
        "was_imported": False,
        "import_status": "not_needed",
        "data": data
    }


@app.get("/episodes")
async def episodes(request: Request):
    # 🔥 Ambil raw query agar slug tidak terpotong
    raw_query = str(request.url.query)
    slug_part = ""

    for param in raw_query.split("&"):
        if param.startswith("slug="):
            slug_part = unquote(param[len("slug="):])
            break

    # Auto-resolve jika masih import slug
    if slug_part.startswith("import?") or slug_part == "import":
        resolve = await resolve_import_internal(slug_part)
        if not resolve.get("final_slug"):
            return {"error": "Gagal resolve import slug", "total_episode": 0}
        slug_part = resolve["final_slug"]

    return {
        "slug": slug_part,
        "total_episode": get_total_episodes(slug_part)
    }


@app.get("/videos")
def videos(slug: str):
    return {"slug": slug, "data": get_all_video_links(slug)}


@app.get("/video")
async def video(request: Request, ep: int = 1):
    # 🔥 Ambil raw query agar slug tidak terpotong
    raw_query = str(request.url.query)
    slug_part = ""

    for param in raw_query.split("&"):
        if param.startswith("slug="):
            slug_part = unquote(param[len("slug="):])
            break

    # Auto-resolve jika masih import slug
    if slug_part.startswith("import?") or slug_part == "import":
        resolve = await resolve_import_internal(slug_part)
        if not resolve.get("final_slug"):
            return {"error": "Gagal resolve import slug", "video_url": None}
        slug_part = resolve["final_slug"]

    return {
        "slug": slug_part,
        "episode": ep,
        "video_url": get_video_src(slug_part, ep)
    }


@app.get("/stream")
async def stream(request: Request, url: str):
    decoded_url = unquote(unquote(url))

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": BASE_DOMAIN,
        "Origin": BASE_DOMAIN,
        "Accept": "*/*",
    }

    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
        async with client.stream("GET", decoded_url, headers=headers) as r:
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
        "data": {"items": data[start:end]}
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
