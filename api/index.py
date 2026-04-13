from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from mangum import Mangum
import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse

app = FastAPI()
handler = Mangum(app)

BASE_DOMAIN = "https://narto-drama.com"
LIST_URL = f"{BASE_DOMAIN}/?lang=id-ID"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
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


# =========================
# SCRAPE LIST
# =========================
def scrape_list(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        items = []
        for card in soup.find_all("a", class_="card-link-overlay"):
            title = card.get_text(strip=True)
            href = card.get("href")

            if href and not href.startswith("http"):
                href = BASE_DOMAIN + href

            if title and href:
                items.append({
                    "title": title,
                    "href": href.split("?")[0],
                    "slug": extract_slug(href)
                })

        return items

    except Exception as e:
        return {"error": str(e)}


# =========================
# TOTAL EPISODE
# =========================
def get_total_episodes(slug: str) -> int:
    try:
        url = f"{BASE_DOMAIN}/{slug}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        episode_links = soup.find_all("a", class_="episode-item")

        max_ep = 0

        for link in episode_links:
            title = link.get("title")
            if title and title.isdigit():
                max_ep = max(max_ep, int(title))
                continue

            text = link.get_text(strip=True)
            match = re.search(r"EP\s*(\d+)", text, re.IGNORECASE)
            if match:
                max_ep = max(max_ep, int(match.group(1)))

        return max_ep

    except:
        return 0


# =========================
# GET VIDEO URL (INTERNAL)
# =========================
def get_video_src_from_episode(url: str, ep: int):
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code != 200:
        return None

    html = resp.text

    match = re.search(r'episodeItemsRaw\s*=\s*(\[\{.*?\}\]);', html, re.DOTALL)
    if not match:
        return None

    try:
        episodes = json.loads(match.group(1))
    except:
        return None

    for item in episodes:
        if int(item.get("number", 0)) == ep:
            return item.get("play_url")

    return None


# =========================
# STREAM VIDEO (🔥 SOLUSI UTAMA)
# =========================
@app.get("/stream")
def stream(slug: str, ep: int):
    try:
        watch_url = f"{BASE_DOMAIN}/detail/watch/{slug}/{ep}?lang=id-ID"

        play_url = get_video_src_from_episode(watch_url, ep)

        if not play_url:
            return {"error": "video not found"}

        full_url = BASE_DOMAIN + play_url.replace("\\/", "/")

        # 🔥 sama seperti Colab
        r = requests.get(full_url, headers=HEADERS, stream=True)

        return StreamingResponse(
            r.iter_content(chunk_size=1024 * 1024),
            media_type=r.headers.get("Content-Type", "video/mp4")
        )

    except Exception as e:
        return {"error": str(e)}


# =========================
# ROUTES TAMBAHAN
# =========================

@app.get("/")
def home():
    return {"message": "API Running 🚀"}


@app.get("/list")
def list_api():
    return scrape_list(LIST_URL)


@app.get("/search")
def search(q: str = Query("")):
    try:
        url = f"{BASE_DOMAIN}/search?lang=id-ID&q={q}"
        return scrape_list(url)
    except Exception as e:
        return {"error": str(e)}


@app.get("/episodes")
def episodes(slug: str):
    if not slug:
        return {"error": "slug is required"}

    total = get_total_episodes(slug)

    return {
        "slug": slug,
        "total_episode": total
    }
