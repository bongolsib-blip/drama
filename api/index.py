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
# SCRAPE LIST (FIX TITLE H3)
# =========================
def scrape_list(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        items = []
        for card in soup.find_all("a", class_="card-link-overlay"):

            # 🔥 FIX: ambil title dari <h3>
            title_tag = card.find("h3")
            title = title_tag.get_text(strip=True) if title_tag else ""

            href = card.get("href")

            if href and not href.startswith("http"):
                href = BASE_DOMAIN + href

            if title and href:
                items.append({
                    "title": title,
                    "href": href.split("?")[0],
                    "slug": extract_slug(href)
                })

        # pagination
        next_btn = soup.find("a", rel="next")
        has_next = True if next_btn else False

        return {
            "items": items,
            "has_next": has_next
        }

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
# VIDEO SCRAPER
# =========================
def get_all_video_links(slug: str):
    try:
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
            else:
                play_url = None

            result.append({
                "episode": int(item.get("number", 0)),
                "video_url": play_url
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


# 🔥 LIST PER PAGE
@app.get("/list")
def list_api(page: int = 1):
    url = f"{BASE_DOMAIN}/?lang=id-ID&page={page}"
    return {
        "page": page,
        "data": scrape_list(url)
    }


# 🔥 AUTO SCRAPE MULTI PAGE
@app.get("/list-all")
def list_all(max_page: int = 5, delay: float = 1):
    all_items = []

    for page in range(1, max_page + 1):
        print(f"[SCRAPE] Page {page}")

        url = f"{BASE_DOMAIN}/?lang=id-ID&page={page}"
        data = scrape_list(url)

        if isinstance(data, dict) and "items" in data:
            all_items.extend(data["items"])

        if not data.get("has_next"):
            break

        time.sleep(delay)

    return {
        "total": len(all_items),
        "pages_scraped": page,
        "data": all_items
    }


# 🔍 SEARCH
@app.get("/search")
def search(q: str = Query("")):
    url = f"{BASE_DOMAIN}/search?lang=id-ID&q={q}"
    return scrape_list(url)


# 📺 EPISODES
@app.get("/episodes")
def episodes(slug: str):
    total = get_total_episodes(slug)
    return {
        "slug": slug,
        "total_episode": total
    }


# 🎬 SINGLE VIDEO
@app.get("/video")
def video(slug: str, ep: int = 1):
    video_url = get_video_src_from_episode(slug, ep)

    return {
        "slug": slug,
        "episode": ep,
        "video_url": video_url
    }


# 🎬 ALL VIDEOS
@app.get("/videos")
def all_videos(slug: str):
    videos = get_all_video_links(slug)

    return {
        "slug": slug,
        "total": len(videos),
        "data": videos
    }


# 🔥 STREAM PROXY
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
