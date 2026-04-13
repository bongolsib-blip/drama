from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from mangum import Mangum
import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse
import time

app = FastAPI()
handler = Mangum(app)

BASE_DOMAIN = "https://narto-drama.com"

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

            # TITLE
            title_tag = card.find("h3", class_="title")
            title = title_tag.get_text(strip=True) if title_tag else ""

            # LINK
            link_tag = card.find("a", class_="card-link-overlay")
            href = link_tag.get("href") if link_tag else None

            if href and not href.startswith("http"):
                href = BASE_DOMAIN + href

            # THUMBNAIL
            img_tag = card.find("img", class_="poster")
            thumbnail = img_tag.get("src") if img_tag else None
            if thumbnail and thumbnail.startswith("/"):
                thumbnail = BASE_DOMAIN + thumbnail

            # TAGS
            tags = [t.get_text(strip=True) for t in card.find_all("a", class_="movie-tag")]

            # EPISODE BADGE
            ep_tag = card.find("div", class_="episode-badge")
            episode_badge = ep_tag.get_text(strip=True) if ep_tag else None

            if title and href:
                items.append({
                    "title": title,
                    "href": href.split("?")[0],
                    "slug": extract_slug(href),
                    "thumbnail": thumbnail,
                    "tags": tags,
                    "episode_badge": episode_badge
                })

        next_btn = soup.find("a", rel="next")

        return {
            "items": items,
            "has_next": True if next_btn else False
        }

    except Exception as e:
        return {"error": str(e)}


# =========================
# DETAIL ENDPOINT 🔥
# =========================
def scrape_detail(slug: str):
    try:
        url = f"{BASE_DOMAIN}/{slug}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # TITLE
        title = soup.find("h1")
        title = title.get_text(strip=True) if title else ""

        # THUMBNAIL
        img = soup.find("img")
        thumbnail = img.get("src") if img else None
        if thumbnail and thumbnail.startswith("/"):
            thumbnail = BASE_DOMAIN + thumbnail

        # SINOPSIS
        desc = soup.find("p")
        description = desc.get_text(strip=True) if desc else ""

        # TAGS
        tags = [t.get_text(strip=True) for t in soup.find_all("a", class_="movie-tag")]

        # TOTAL EPISODE
        episodes = soup.find_all("a", class_="episode-item")
        total_episode = len(episodes)

        return {
            "title": title,
            "thumbnail": thumbnail,
            "description": description,
            "tags": tags,
            "total_episode": total_episode
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


def get_video_src(slug: str, ep: int):
    videos = get_all_video_links(slug)
    for v in videos:
        if v["episode"] == ep:
            return v["video_url"]
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
    r = requests.get(url, headers=STREAM_HEADERS, stream=True)

    return StreamingResponse(
        r.iter_content(chunk_size=1024),
        media_type=r.headers.get("Content-Type")
    )
