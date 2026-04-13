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

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

STREAM_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": BASE_DOMAIN,
    "Origin": BASE_DOMAIN,
    "Accept": "*/*"
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
# 🔥 EXTRACT M3U8
# =========================
def extract_m3u8_from_play_url(play_url: str):
    try:
        full_url = BASE_DOMAIN + play_url.replace("\\/", "/")

        resp = requests.get(
            full_url,
            headers=STREAM_HEADERS,
            allow_redirects=False,
            timeout=10
        )

        # CASE 1: redirect
        if "Location" in resp.headers:
            redirect_url = resp.headers["Location"]
            if ".m3u8" in redirect_url:
                return redirect_url

        # CASE 2: response text
        if ".m3u8" in resp.text:
            for line in resp.text.splitlines():
                if ".m3u8" in line:
                    return line

        return None

    except Exception as e:
        print("ERROR extract m3u8:", e)
        return None


# =========================
# CORE: GET VIDEO LINKS
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

            m3u8_url = None
            if play_url:
                m3u8_url = extract_m3u8_from_play_url(play_url)

            result.append({
                "episode": int(item.get("number", 0)),
                "m3u8": m3u8_url
            })

        return result

    except Exception as e:
        print("ERROR:", e)
        return []


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
