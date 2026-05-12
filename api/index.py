from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from mangum import Mangum
from fastapi.responses import Response, StreamingResponse
from urllib.parse import urljoin, quote
import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse, parse_qs, urlencode, unquote, quote
import time
import httpx
import asyncio

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
CACHE_TTL = 60 * 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_DOMAIN
}

PROVIDERS = [
    "shortmax", "dramabox", "dramabite", "dramawave", "dramanova",
    "netshort", "reelshort", "idrama", "melolo", "starshort",
    "goodshort", "flextv", "fundrama", "microdrama", "bilitv",
    "vigloo", "velolo", "reelala", "stardusttv", "flickreels", "reelife"
]

video_cache = {}
VIDEO_CACHE_TTL = 600

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
    if not genres: genres.add("Drama")
    return list(genres)

VALID_GENRES = {
    "Romance", "Drama", "Comedy", "Action", "Fantasy",
    "Family", "Business", "Crime", "Mystery", "Sci-Fi"
}

def clean_genres(genres):
    return [g for g in genres if g in VALID_GENRES]

# =========================
# CACHE
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
# SEARCH HTML (lokal)
# =========================
async def scrape_local_search(q: str, page: int = 1):
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            html_resp = requests.get(
                f"{BASE_DOMAIN}/search",
                params={'q': q, 'lang': 'id-ID', 'page': page},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": f"{BASE_DOMAIN}/"
                }
            )
            if html_resp.status_code != 200:
                return []

            soup = BeautifulSoup(html_resp.text, "html.parser")
            items = []

            for card in soup.find_all("article", class_="card"):
                title_tag = card.find("h3", class_="title")
                link_tag = card.find("a", class_="card-link-overlay")
                img_tag = card.find("img", class_="poster")

                if not title_tag or not link_tag:
                    continue

                raw_href = link_tag.get("href", "")
                title = title_tag.get_text(strip=True)

                if not raw_href or "iklan" in title.lower():
                    continue

                clean_href = raw_href.split("?")[0]
                slug = extract_slug(clean_href)
                full_url = f"{BASE_DOMAIN}{clean_href}" if clean_href.startswith("/") else clean_href

                thumb = img_tag.get("src") if img_tag else None
                if thumb and thumb.startswith("/"):
                    thumb = f"{BASE_DOMAIN}{thumb}"

                items.append({
                    "title": title,
                    "href": full_url,
                    "slug": slug,
                    "type": "local",
                    "thumbnail": thumb,
                    "status": card.find("div", class_="card-ep").get_text(strip=True) if card.find("div", class_="card-ep") else "",
                    "tags": [t.get_text(strip=True) for t in card.find_all("a", class_="movie-tag")]
                })

            return items
    except Exception as e:
        print(f"[search-html] Error: {e}")
        return []

# =========================
# FETCH SATU PROVIDER
# =========================
async def fetch_one_provider(q: str, provider: str):
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = requests.get(
                f"{BASE_DOMAIN}/search/providers/retry",
                params={
                    'q': q,
                    'providers': provider,
                    'limit': 100,
                    'full_search': 1,
                    'lang': 'id-ID'
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{BASE_DOMAIN}/search?q={q}&lang=id-ID",
                    "Origin": BASE_DOMAIN,
                }
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            raw_items = data.get("items", [])

            results = []
            for item in raw_items:
                # 🔥 Filter hanya bahasa Indonesia
                lang = item.get("language_code", "")
                if lang and lang.lower() not in ("id-id", "id"):
                    continue

                original_url = item.get("url", "")
                poster = item.get("poster_url", "")
                if poster and poster.startswith("/"):
                    poster = f"{BASE_DOMAIN}{poster}"

                parsed = urlparse(original_url)
                slug = f"import?{parsed.query}" if "/search/import" in original_url else extract_slug(original_url)

                results.append({
                    "title": item.get("title", ""),
                    "href": original_url,
                    "slug": slug,
                    "type": "import",
                    "thumbnail": poster,
                    "status": "",
                    "tags": item.get("tags", []),
                    "description": item.get("description", ""),
                    "relevance_score": item.get("relevance_score", 0),
                    "provider": provider,
                    "language_code": lang
                })

            return results
    except Exception as e:
        print(f"[provider:{provider}] error: {e}")
        return []

# =========================
# SEARCH FULL (HTML + providers)
# =========================
async def scrape_full_search(q: str, page: int = 1):
    seen_titles = set()
    items = []

    # HTML lokal dulu
    local_items = await scrape_local_search(q, page)
    for item in local_items:
        title_key = item["title"].lower().strip()
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            items.append(item)

    # Provider satu-satu hanya di page 1
    if page == 1:
        semaphore = asyncio.Semaphore(3)

        async def fetch_with_sem(provider):
            async with semaphore:
                result = await fetch_one_provider(q, provider)
                time.sleep(0.2)
                return result

        tasks = [fetch_with_sem(p) for p in PROVIDERS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for provider_items in results:
            if isinstance(provider_items, Exception) or not provider_items:
                continue
            for item in provider_items:
                title_key = item["title"].lower().strip()
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    items.append(item)

    local_items_final = [i for i in items if i["type"] == "local"]
    import_items_final = sorted(
        [i for i in items if i["type"] == "import"],
        key=lambda x: x.get("relevance_score", 0),
        reverse=True
    )

    return {
        "query": q,
        "current_page": page,
        "has_next": False,
        "count": len(items),
        "local_count": len(local_items_final),
        "import_count": len(import_items_final),
        "items": local_items_final + import_items_final
    }

# =========================
# ENDPOINT BARU: search per provider (untuk streaming di frontend)
# =========================
@app.get("/search-provider")
async def search_provider(q: str, provider: str):
    """Fetch satu provider — dipanggil frontend satu per satu agar bisa tampil bertahap"""
    items = await fetch_one_provider(q, provider)
    return {
        "provider": provider,
        "count": len(items),
        "items": items
    }

@app.get("/search-local")
async def search_local(q: str, page: int = 1):
    """Fetch drama lokal dari HTML scrape"""
    items = await scrape_local_search(q, page)
    return {
        "query": q,
        "count": len(items),
        "items": items
    }

# =========================
# RESOLVE IMPORT — dengan retry lebih agresif
# =========================


# =========================
# SCRAPE DETAIL
# =========================
def scrape_detail(slug: str):
    try:
        url = f"{BASE_DOMAIN}/detail/watch/{slug}?lang=id-ID&from=home"
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

def get_video_src(slug: str, ep: int):
    key = f"{slug}_{ep}"
    now = time.time()

    if key in video_cache:
        cached = video_cache[key]
        if now - cached["time"] < VIDEO_CACHE_TTL:
            return cached["url"]

    refresh_url = (
        f"{BASE_DOMAIN}/detail/watch/{slug}/{ep}/refresh-source"
        "?lang=id-ID&force=1"
    )

    for _ in range(5):
        try:
            resp = requests.get(
                refresh_url,
                headers=HEADERS,
                timeout=10
            )

            if resp.status_code == 200:
                data = resp.json()

                play_url = data.get("play_url")
                direct_url = data.get("direct_play_url")

                final_url = None

                # ✅ PRIORITAS:
                # pakai play_url dulu karena biasanya ada subtitle
                if play_url:

                    # 🔥 kalau stream/proxy
                    if "/stream/proxy" in play_url:
                
                        try:
                            proxy_url = (
                                "https://narto-drama.com" + play_url
                            )
                
                            r = requests.get(
                                proxy_url,
                                headers={
                                    **HEADERS,
                                    "Referer": "https://narto-drama.com/",
                                    "Origin": "https://narto-drama.com",
                                },
                                allow_redirects=True,
                                timeout=15,
                                stream=True,
                            )
                
                            # 🔥 ambil URL final hasil redirect
                            final_real_url = r.url
                
                            # kalau berhasil redirect ke mp4/m3u8
                            if final_real_url and final_real_url != proxy_url:
                                final_url = final_real_url
                            else:
                                final_url = direct_url or play_url
                
                        except Exception as e:
                            print("proxy resolve error:", e)
                            final_url = direct_url or play_url
                
                    else:
                        final_url = play_url

                # 🔥 fallback kalau tidak ada
                elif direct_url:
                    final_url = direct_url

                if final_url:
                    video_cache[key] = {
                        "url": final_url,
                        "time": now
                    }

                    return final_url

        except Exception as e:
            print("get_video_src error:", e)

        time.sleep(1.5)

    return None
def get_total_episodes(slug: str):
    url = f"{BASE_DOMAIN}/detail/watch/{slug}?lang=id-ID"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")
    episodes = soup.find_all("a", class_="episode-item")
    return len(episodes)

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
        result.append({"episode": int(item.get("number", 0)), "video_url": play_url})
    return result

# =========================
# ROUTES
# =========================

@app.get("/")
def home():
    return {"status": "API Running 🚀"}

@app.get("/list")
def list_api(page: int = 1):
    return {"page": page, "data": scrape_list(f"{BASE_DOMAIN}/?lang=id-ID&page={page}")}

@app.get("/list-all")
def list_all(max_page: int = 5, delay: float = 1):
    all_items = []
    for page in range(1, max_page + 1):
        data = scrape_list(f"{BASE_DOMAIN}/?lang=id-ID&page={page}")
        if "items" in data:
            all_items.extend(data["items"])
        if not data.get("has_next"):
            break
        time.sleep(delay)
    return {"total": len(all_items), "data": all_items}

@app.get("/search")
async def search(q: str):
    items = await scrape_local_search(q)
    return {"status": "success", "count": len(items), "items": items}

@app.get("/search-full")
async def search_full(q: str, page: int = 1):
    return await scrape_full_search(q, page)

@app.get("/check-import")
async def check_import(request: Request):
    raw_query = str(request.url.query)
    
    if raw_query.startswith("slug="):
        decoded_slug = unquote(raw_query[len("slug="):])
    else:
        decoded_slug = unquote(request.query_params.get("slug", ""))

    if not decoded_slug.startswith("import?"):
        return {"status": "not_import", "final_slug": decoded_slug}

    query_part = decoded_slug[len("import?"):]
    import_url = f"{BASE_DOMAIN}/search/import?{query_part}"

    try:
        session = requests.Session()
        session.get(BASE_DOMAIN, headers=HEADERS, timeout=8)

        # STEP 1: Hit import URL → dapat task_id dari response atau redirect
        resp = session.get(import_url, headers=HEADERS, timeout=8, allow_redirects=False)
        
        print(f"[check-import] status={resp.status_code}")
        print(f"[check-import] headers={dict(resp.headers)}")
        print(f"[check-import] body preview={resp.text[:1000]}")

        # Cek redirect langsung
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if "/detail/watch/" in location:
                return {"status": "success", "final_slug": extract_slug(location.split("?")[0])}

        # STEP 2: Cari task_id dari HTML
        soup = BeautifulSoup(resp.text, "html.parser")
        
        task_id = None
        
        # Cari di script tag
        for script in soup.find_all("script"):
            text = script.get_text()
            # Cari pola task UUID
            match = re.search(r'task["\']?\s*[:=]\s*["\']([a-f0-9\-]{36})["\']', text)
            if match:
                task_id = match.group(1)
                break
            # Cari pola lain
            match2 = re.search(r'["\']([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})["\']', text)
            if match2:
                task_id = match2.group(1)
                break

        # Cari di data attribute
        if not task_id:
            el = soup.find(attrs={"data-task": True})
            if el:
                task_id = el["data-task"]

        # Cari di meta tag
        if not task_id:
            meta = soup.find("meta", attrs={"name": "task-id"})
            if meta:
                task_id = meta.get("content")

        print(f"[check-import] task_id={task_id}")

        if not task_id:
            return {"status": "pending", "final_slug": None, "debug": "no task_id found"}

        # STEP 3: Poll status endpoint
        status_url = f"{BASE_DOMAIN}/search/import/status?task={task_id}&lang=id-ID"
        
        for attempt in range(5):
            time.sleep(1.5)
            
            try:
                status_resp = session.get(status_url, headers=HEADERS, timeout=8)
                print(f"[import-status] attempt={attempt+1} status={status_resp.status_code} body={status_resp.text[:300]}")
                
                if status_resp.status_code == 200:
                    try:
                        status_data = status_resp.json()
                        
                        # Cek berbagai kemungkinan field response
                        # Kemungkinan 1: ada field "url" atau "redirect"
                        redirect_url = (
                            status_data.get("url") or
                            status_data.get("redirect") or
                            status_data.get("redirect_url") or
                            status_data.get("drama_url") or
                            status_data.get("watch_url")
                        )
                        if redirect_url and "/detail/watch/" in redirect_url:
                            return {
                                "status": "success",
                                "final_slug": extract_slug(redirect_url.split("?")[0])
                            }

                        # Kemungkinan 2: ada field "slug"
                        slug_val = status_data.get("slug") or status_data.get("drama_slug")
                        if slug_val:
                            return {"status": "success", "final_slug": slug_val}

                        # Kemungkinan 3: status "done"/"complete" dengan data lain
                        st = status_data.get("status", "").lower()
                        if st in ("done", "complete", "success", "finished"):
                            # Cari slug di semua field
                            for val in status_data.values():
                                if isinstance(val, str) and "/detail/watch/" in val:
                                    return {
                                        "status": "success",
                                        "final_slug": extract_slug(val.split("?")[0])
                                    }
                            # Kembalikan raw data untuk debug
                            return {
                                "status": "success_raw",
                                "final_slug": None,
                                "raw": status_data
                            }

                        # Masih pending
                        if st in ("pending", "processing", "queued", "running"):
                            continue
                            
                    except Exception as je:
                        print(f"[import-status] JSON parse error: {je}, raw={status_resp.text[:200]}")
                        
            except Exception as e:
                print(f"[import-status] Error: {e}")

        return {"status": "pending", "final_slug": None}

    except Exception as e:
        print(f"[check-import] Error: {e}")
        return {"status": "error", "message": str(e), "final_slug": None}




@app.get("/detail")
async def detail(request: Request):
    raw_query = str(request.url.query)
    if raw_query.startswith("slug="):
        full_slug = unquote(raw_query[len("slug="):])
    else:
        full_slug = request.query_params.get("slug", "")

    if full_slug.startswith("import?"):
        return {
            "error": "Import belum selesai",
            "final_slug": None
        }
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
    raw_query = str(request.url.query)
    slug_part = ""
    for param in raw_query.split("&"):
        if param.startswith("slug="):
            slug_part = unquote(param[len("slug="):])
            break
    if slug_part.startswith("import?"):
        return {
            "error": "Gunakan final slug",
            "video_url": None
        }
        if not resolve.get("final_slug"):
            return {"error": "Gagal resolve import slug", "total_episode": 0}
        slug_part = resolve["final_slug"]
    return {"slug": slug_part, "total_episode": get_total_episodes(slug_part)}

@app.get("/videos")
def videos(slug: str):
    return {"slug": slug, "data": get_all_video_links(slug)}

@app.get("/video")
async def video(request: Request, ep: int = 1):
    raw_query = str(request.url.query)
    slug_part = ""
    for param in raw_query.split("&"):
        if param.startswith("slug="):
            slug_part = unquote(param[len("slug="):])
            break
    if slug_part.startswith("import?") or slug_part == "import":
        resolve = await resolve_import_internal(slug_part)
        if not resolve.get("final_slug"):
            return {"error": "Gagal resolve import slug", "video_url": None}
        slug_part = resolve["final_slug"]
    return {"slug": slug_part, "episode": ep, "video_url": get_video_src(slug_part, ep)}

@app.get("/stream")
async def stream(request: Request, url: str):
    decoded_url = unquote(unquote(url))
    fetch_headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": BASE_DOMAIN,
        "Origin": BASE_DOMAIN,
        "Accept": "*/*",
    }
    range_header = request.headers.get("range")
    if range_header:
        fetch_headers["Range"] = range_header

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        if ".m3u8" in decoded_url:
            resp = requests.get(decoded_url, headers=fetch_headers)
            text = resp.text
            base_url = decoded_url.rsplit("/", 1)[0] + "/"
            rewritten_lines = []
            for line in text.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    abs_url = stripped if stripped.startswith("http") else base_url + stripped
                    proxied = f"https://drama-liart.vercel.app/stream?url={quote(abs_url, safe='')}"
                    rewritten_lines.append(proxied)
                else:
                    rewritten_lines.append(line)
            return Response(
                content="\n".join(rewritten_lines),
                media_type="application/vnd.apple.mpegurl",
                headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"}
            )

        async with client.stream("GET", decoded_url, headers=fetch_headers) as r:
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
    return {"genre": genre, "total": len(data), "page": page, "data": {"items": data[start:end]}}

@app.get("/filter")
def filter_api(genre: str = None, keyword: str = None, page: int = 1, limit: int = 20):
    ensure_cache()
    data = ALL_DRAMAS
    if genre:
        data = GENRE_INDEX.get(genre, [])
    if keyword:
        keyword = keyword.lower()
        data = [d for d in data if keyword in d["title"].lower()]
    start = (page - 1) * limit
    end = start + limit
    return {"total": len(data), "page": page, "results": data[start:end]}

@app.get("/debug-search")
async def debug_search(q: str, page: int = 1):
    url = f"{BASE_DOMAIN}/search"
    params = {'q': q, 'lang': 'id-ID', 'page': page}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{BASE_DOMAIN}/"
    }
    async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
        try:
            resp = requests.get(url, params=params)
            soup = BeautifulSoup(resp.text, "html.parser")
            all_cards = soup.find_all("article", class_="card")
            raw_hrefs = []
            for card in all_cards:
                link = card.find("a", class_="card-link-overlay")
                title = card.find("h3", class_="title")
                raw_hrefs.append({
                    "title": title.get_text(strip=True) if title else "",
                    "href": link.get("href", "") if link else "",
                    "is_import": "/search/import" in (link.get("href", "") if link else "")
                })
            pager = soup.find("div", class_="pager")
            return {
                "status_code": resp.status_code,
                "total_cards_found": len(all_cards),
                "raw_hrefs": raw_hrefs,
                "pager_html": str(pager) if pager else "TIDAK ADA PAGER",
            }
        except Exception as e:
            return {"error": str(e)}

# Simpan task_id sementara di memory
import_tasks = {}  # {slug_key: task_id}
resolved_cache = {}

@app.get("/start-import")
async def start_import(request: Request):

    print("\n================ START IMPORT ================")

    raw_query = str(request.url.query)
    print(f"[start-import] raw_query={raw_query}")

    if raw_query.startswith("slug="):
        decoded_slug = unquote(raw_query[len("slug="):])
    else:
        decoded_slug = unquote(request.query_params.get("slug", ""))

    print(f"[start-import] decoded_slug={decoded_slug}")

    if not decoded_slug.startswith("import?"):
        print("[start-import] bukan import slug")

        return {
            "status": "not_import",
            "final_slug": decoded_slug
        }

    query_part = decoded_slug[len("import?"):]
    import_url = f"{BASE_DOMAIN}/search/import?{query_part}"

    print(f"[start-import] import_url={import_url}")

    try:
        session = requests.Session()

        home_resp = session.get(
            BASE_DOMAIN,
            headers=HEADERS,
            timeout=10
        )

        print(f"[start-import] home status={home_resp.status_code}")

        resp = session.get(
            import_url,
            headers=HEADERS,
            timeout=15,
            allow_redirects=False
        )

        print(f"[start-import] import status={resp.status_code}")
        print(f"[start-import] final url={resp.url}")

        print(f"[start-import] headers={dict(resp.headers)}")

        print(f"[start-import] body preview=\n{resp.text[:1500]}")

        # redirect langsung
        if resp.status_code in (301, 302, 303, 307, 308):

            location = resp.headers.get("location", "")

            print(f"[start-import] redirect location={location}")

            if "/detail/watch/" in location:

                final_slug = extract_slug(location.split("?")[0])

                print(f"[start-import] SUCCESS redirect final_slug={final_slug}")

                return {
                    "status": "success",
                    "final_slug": final_slug
                }

        soup = BeautifulSoup(resp.text, "html.parser")

        task_id = None

        # scan semua script
        for idx, script in enumerate(soup.find_all("script")):

            text = script.get_text()

            print(f"\n[start-import] SCRIPT {idx}")
            print(text[:1000])

            match = re.search(
                r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
                text
            )

            if match:
                task_id = match.group(1)

                print(f"[start-import] TASK FOUND={task_id}")

                break

        if not task_id:

            print("[start-import] task_id TIDAK ditemukan")

            return {
                "status": "error",
                "message": "task_id tidak ditemukan"
            }

        cookies = dict(session.cookies)

        print(f"[start-import] cookies={cookies}")

        import_tasks[decoded_slug] = {
            "task_id": task_id,
            "cookies": cookies
        }

        print(f"[start-import] import_tasks keys={list(import_tasks.keys())}")

        print("=============== END START IMPORT ===============\n")

        return {
            "status": "pending",
            "task_id": task_id,
            "cookies": cookies
        }

    except Exception as e:

        print(f"[start-import] ERROR={e}")

        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/poll-import")
async def poll_import(task_id: str):

    try:
        status_url = (
            f"{BASE_DOMAIN}/search/import/status"
            f"?task={task_id}&lang=id-ID"
        )

        print(f"[poll-import] TASK: {task_id}")
        print(f"[poll-import] URL: {status_url}")

        resp = requests.get(
            status_url,
            headers=HEADERS,
            timeout=8,
            allow_redirects=True
        )

        print(f"[poll-import] STATUS CODE: {resp.status_code}")
        print(f"[poll-import] CONTENT TYPE: {resp.headers.get('content-type')}")

        raw_text = resp.text[:1000]

        print(f"[poll-import] RAW RESPONSE:")
        print(raw_text)

        # =========================
        # CEK APAKAH JSON
        # =========================
        try:
            data = resp.json()

        except Exception as json_error:

            print(f"[poll-import] JSON ERROR: {json_error}")

            return {
                "status": "processing",
                "message": "response belum json",
                "raw_preview": raw_text[:200]
            }

        print(f"[poll-import] JSON DATA: {data}")

        status = str(data.get("status", "")).lower()

        redirect_url = (
            data.get("redirect_url")
            or data.get("url")
            or data.get("redirect")
            or ""
        )

        # =========================
        # SUCCESS
        # =========================
        if "/detail/watch/" in redirect_url:

            return {
                "status": "success",
                "final_slug": extract_slug(
                    redirect_url.split("?")[0]
                )
            }

        # =========================
        # STATUS SUCCESS
        # =========================
        if status in (
            "done",
            "success",
            "finished",
            "complete"
        ):

            # scan semua field
            for val in data.values():

                if (
                    isinstance(val, str)
                    and "/detail/watch/" in val
                ):

                    return {
                        "status": "success",
                        "final_slug": extract_slug(
                            val.split("?")[0]
                        )
                    }

            return {
                "status": "success_unknown",
                "raw": data
            }

        # =========================
        # MASIH PROCESSING
        # =========================
        return {
            "status": "processing",
            "message": data.get("message", ""),
            "progress": (
                f"{data.get('progress_current', 0)}"
                f"/{data.get('progress_total', 0)}"
            )
        }

    except Exception as e:

        print(f"[poll-import] ERROR: {e}")

        return {
            "status": "error",
            "message": str(e)
        }
@app.get("/proxy-hls")
async def proxy_hls(url: str):

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": url,
        "Origin": url.split("/")[0] + "//" + url.split("/")[2],
    }

    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get(url, headers=headers)

    content_type = r.headers.get("content-type", "")

    # ==================================================
    # BINARY FILE (ts, m4s, mp4, aac)
    # ==================================================
    if ".m3u8" not in url:

        return Response(
            content=r.content,
            media_type=content_type,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=3600",
            }
        )

    # ==================================================
    # PLAYLIST M3U8
    # ==================================================
    text = r.text

    new_lines = []

    for line in text.splitlines():

        line = line.strip()

        # rewrite URI="..."
        if 'URI="' in line:

            def replace_uri(match):
                original = match.group(1)

                absolute = urljoin(url, original)

                proxied = (
                    f'/proxy-hls?url='
                    f'{quote(absolute, safe="")}'
                )

                return f'URI="{proxied}"'

            line = re.sub(
                r'URI="([^"]+)"',
                replace_uri,
                line
            )

            new_lines.append(line)
            continue

        # comment
        if line.startswith("#") or not line:
            new_lines.append(line)
            continue

        # absolute
        if line.startswith("http"):

            proxied = (
                f'/proxy-hls?url='
                f'{quote(line, safe="")}'
            )

            new_lines.append(proxied)

        # relative
        else:

            absolute = urljoin(url, line)

            proxied = (
                f'/proxy-hls?url='
                f'{quote(absolute, safe="")}'
            )

            new_lines.append(proxied)

    fixed_playlist = "\n".join(new_lines)

    return Response(
        content=fixed_playlist,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache",
        }
    )

@app.get("/proxy-segment")
def proxy_segment(url: str):

    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://narto-drama.com/",
        "Origin": "https://narto-drama.com"
    }

    r = requests.get(
        url,
        headers=headers,
        stream=True,
        timeout=20
    )

    return StreamingResponse(
        r.iter_content(chunk_size=8192),
        media_type=r.headers.get("content-type", "video/mp2t")
    )

