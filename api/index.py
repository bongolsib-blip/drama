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
    "User-Agent": "Mozilla/5.0"
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
# CORE: AMBIL VIDEO
# =========================
def get_all_video_links(slug: str):
    try:
        url = f"{BASE_DOMAIN}/detail/watch/{slug}/1?from=home?lang=id-ID/"
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
                full_url = play_url
            else:
                full_url = None

            result.append({
                "episode": int(item.get("number", 0)),
                "video_url": full_url
            })

        return result

    except Exception as e:
        print("ERROR:", e)
        return []


def get_video_src_from_episode(slug: str, ep: int):
    videos = get_all_video_links(slug)

    for item in videos:
        if item["episode"] == ep:
            return item["video_url"]

    return None


# =========================
# ROUTES
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


@app.get("/video")
def video(slug: str, ep: int = 1):
    if not slug:
        return {"error": "slug is required"}

    video_url = get_video_src_from_episode(slug, ep)

    return {
        "slug": slug,
        "episode": ep,
        "video_url": video_url
    }


@app.get("/videos")
def all_videos(slug: str):
    if not slug:
        return {"error": "slug is required"}

    videos = get_all_video_links(slug)

    return {
        "slug": slug,
        "total": len(videos),
        "data": videos
    }


# =========================
# 🔥 STREAM PROXY (ANTI 403)
# =========================
@app.get("/stream")
def stream(url: str):
    try:
        r = requests.get(url, headers=STREAM_HEADERS, stream=True)

        return StreamingResponse(
            r.iter_content(chunk_size=1024),
            media_type=r.headers.get("Content-Type")
        )

    except Exception as e:
        return {"error": str(e)}
