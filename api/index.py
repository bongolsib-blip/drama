from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from mangum import Mangum
import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse
import time

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🔥 bisa dibatasi nanti
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

# =========================
# genere
# =========================
def normalize_genres(tags, title):
    genres = set()

    # 🔥 mapping ke 10 genre utama
    tag_map = {
        # Romance
        "romantis": "Romance",
        "romansa": "Romance",
        "cinta": "Romance",
        "love": "Romance",
        "nikah": "Romance",

        # Drama
        "ceo": "Drama",
        "kantoran": "Drama",
        "kehidupan": "Drama",
        "modern": "Drama",

        # Comedy
        "komedi": "Comedy",
        "lucu": "Comedy",
        "kocak": "Comedy",

        # Action
        "aksi": "Action",
        "dewa perang": "Action",
        "perang": "Action",
        "pertarungan": "Action",

        # Fantasy
        "fantasi": "Fantasy",
        "sistem": "Fantasy",
        "reinkarnasi": "Fantasy",
        "time travel": "Fantasy",
        "kelahiran kembali": "Fantasy",
        "kekuatan super": "Fantasy",
        "transmigrasi": "Fantasy",

        # Family
        "keluarga": "Family",
        "anak": "Family",
        "ayah": "Family",
        "ibu": "Family",

        # Business
        "bisnis": "Business",
        "miliarder": "Business",
        "konglomerat": "Business",
        "kaya": "Business",
        "direktur": "Business",

        # Crime
        "mafia": "Crime",
        "kriminal": "Crime",
        "penjara": "Crime",
        "pembunuh": "Crime",

        # Mystery
        "misteri": "Mystery",
        "rahasia": "Mystery",
        "detektif": "Mystery",

        # Sci-Fi
        "kiamat": "Sci-Fi",
        "apokalips": "Sci-Fi",
        "monster": "Sci-Fi",
        "alien": "Sci-Fi"
    }

    # =========================
    # dari TAG
    # =========================
    for tag in tags:
        t = tag.lower()

        for key, val in tag_map.items():
            if key in t:
                genres.add(val)

    # =========================
    # fallback dari JUDUL 🔥
    # =========================
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

    # =========================
    # fallback terakhir
    # =========================
    if not genres:
        genres.add("Drama")

    return list(genres)

# -------------------
VALID_GENRES = {
    "Romance","Drama","Comedy","Action","Fantasy",
    "Family","Business","Crime","Mystery","Sci-Fi"
}

def clean_genres(genres):
    return [g for g in genres if g in VALID_GENRES]

# ---------------

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
            # =========================
            # GENRE PROCESSING 🔥
            # =========================
            genres = normalize_genres(item["tags"], item["title"])
            genres = clean_genres(genres)
            item["genres"] = genres

            # =========================
            # SAVE
            # =========================
            ALL_DRAMAS.append(item)

            for g in genres:
                if g not in GENRE_INDEX:
                    GENRE_INDEX[g] = []
                GENRE_INDEX[g].append(item)

        if not data.get("has_next"):
            break

        time.sleep(delay)

    LAST_UPDATE = time.time()
# -----------------

def ensure_cache():
    global LAST_UPDATE

    if time.time() - LAST_UPDATE > CACHE_TTL or not ALL_DRAMAS:
        build_index()

# ----------------

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

        # =========================
        # 🔥 NEXT PAGE FIX
        # =========================
        has_next = False

        pager = soup.find("div", class_="pager")
        if pager:
            next_btn = pager.find("a", class_="pager-link", string=lambda x: x and "Next" in x)
            if next_btn:
                has_next = True

        return {
            "items": items,
            "has_next": has_next
        }

    except Exception as e:
        return {"error": str(e)}


# =========================
# DETAIL ENDPOINT 🔥
# =========================

def scrape_detail(slug: str):
    try:
        url = f"{BASE_DOMAIN}/detail/watch/{slug}?lang=id-ID&from=home"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # =========================
        # TITLE (FIXED)
        # =========================
        title_tag = soup.find("h1", class_="movie-title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # =========================
        # EPISODE INFO (FIXED)
        # =========================
        sub_tag = soup.find("p", class_="movie-sub")
        episode_text = sub_tag.get_text(" ", strip=True) if sub_tag else ""

        # extract angka episode
        total_episode = 0
        match = re.search(r"(\d+)\s*Episode", episode_text)
        if match:
            total_episode = int(match.group(1))

        # =========================
        # DESCRIPTION (FIXED)
        # =========================
        desc_tag = soup.find("div", class_="movie-desc")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # =========================
        # TAGS (FIXED)
        # =========================
        tags = []
        for tag in soup.find_all("a", class_="movie-tag-pill"):
            tags.append(tag.get_text(strip=True))

        # =========================
        # THUMBNAIL (fallback aman)
        # =========================
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

def get_video_src(slug: str, ep: int):
    try:
        # =========================
        # STEP 1: method lama
        # =========================
        videos = get_all_video_links(slug)

        for v in videos:
            if v["episode"] == ep:
                url = v["video_url"]

                # kalau bukan proxy → langsung pakai
                if url and not url.startswith("/stream/proxy"):
                    return url

        # =========================
        # STEP 2: fallback + retry 🔥
        # =========================
        key = f"{slug}_{ep}"
        if key in video_cache:
            return video_cache[key]
        
        refresh_url = f"{BASE_DOMAIN}/detail/watch/{slug}/{ep}/refresh-source?lang=id-ID&force=1"

        for _ in range(5):  # retry 5x
            try:
                resp = requests.get(refresh_url, headers=HEADERS, timeout=10)
                data = resp.json()

                url = data.get("direct_play_url")

                if url and "m3u8" in url:
                    video_cache[key] = url
                    return url

            except:
                pass

            time.sleep(2)

        return None

    except Exception as e:
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
    return {
        "page": page,
        "data": scrape_list(url)
    }


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

    return {
        "total": len(all_items),
        "data": all_items
    }


@app.get("/search")
def search(q: str):
    url = f"{BASE_DOMAIN}/search?lang=id-ID&q={q}"
    return scrape_list(url)


@app.get("/detail")
def detail(slug: str):
    return {
        "slug": slug,
        "data": scrape_detail(slug)
    }


@app.get("/episodes")
def episodes(slug: str):
    return {
        "slug": slug,
        "total_episode": get_total_episodes(slug)
    }


@app.get("/videos")
def videos(slug: str):
    return {
        "slug": slug,
        "data": get_all_video_links(slug)
    }


@app.get("/video")
def video(slug: str, ep: int = 1):
    return {
        "slug": slug,
        "episode": ep,
        "video_url": get_video_src(slug, ep)
    }


@app.get("/stream")
def stream(url: str):
    try:
        r = requests.get(url, headers=STREAM_HEADERS, stream=True, timeout=10)

        return StreamingResponse(
            r.iter_content(chunk_size=1024),
            media_type=r.headers.get("Content-Type", "application/vnd.apple.mpegurl")
        )

    except:
        return {"error": "stream failed"}

@app.get("/genres")
def get_genres():
    ensure_cache()
    return {
        "genres": list(GENRE_INDEX.keys())
    }

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
        "results": data[start:end]
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
