from fastapi import FastAPI, Query
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

headers = {
    "User-Agent": "Mozilla/5.0"
}

# =========================
# UTIL
# =========================
def extract_slug(url: str) -> str:
    try:
        if not url:
            return ""

        parsed = urlparse(url)
        path = parsed.path.strip("/")

        if not path:
            return ""

        return path.split("/")[-1]
    except:
        return ""


def build_url_from_slug(slug: str):
    return f"{BASE_DOMAIN}/{slug}"


# =========================
# SCRAPE LIST
# =========================
def scrape_list(url):
    try:
        resp = requests.get(url, headers=headers, timeout=10)
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
                    "href": href.split("?")[0],  # 🔥 bersihkan query
                    "slug": extract_slug(href)
                })

        return items

    except Exception as e:
        return {"error": str(e)}


# =========================
# TOTAL EPISODE
# =========================
def get_total_episodes(url: str) -> int:
    try:
        resp = requests.get(url, headers=headers, timeout=10)
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
# AMBIL SEMUA DATA EPISODE
# =========================
def get_all_episode_data(url: str):
    try:
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code != 200:
            return []

        html = resp.text

        match = re.search(r'episodeItemsRaw\s*=\s*(\[\{.*?\}\]);', html, re.DOTALL)
        if not match:
            return []

        return json.loads(match.group(1))

    except:
        return []


# =========================
# VIDEO PER EPISODE
# =========================
def get_video_src_from_episode(url: str, ep: int):
    episodes = get_all_episode_data(url)

    for item in episodes:
        if int(item.get("number", 0)) == ep:
            return item.get("play_url")

    return None


# =========================
# SEMUA VIDEO
# =========================
def get_all_video_links(url: str):
    episodes = get_all_episode_data(url)

    result = []
    for item in episodes:
        result.append({
            "episode": item.get("number"),
            "video_url": item.get("play_url")
        })

    return result


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

    url = build_url_from_slug(slug)
    total = get_total_episodes(url)

    return {
        "slug": slug,
        "total_episode": total
    }


@app.get("/video")
def video(slug: str, ep: int = 1):
    if not slug:
        return {"error": "slug is required"}

    url = build_url_from_slug(slug)
    video = get_video_src_from_episode(url, ep)

    return {
        "slug": slug,
        "episode": ep,
        "video_url": video
    }


@app.get("/videos")
def all_videos(slug: str):
    if not slug:
        return {"error": "slug is required"}

    url = build_url_from_slug(slug)
    videos = get_all_video_links(url)

    return {
        "slug": slug,
        "total": len(videos),
        "data": videos
    }
