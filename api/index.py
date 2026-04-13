from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import requests
from bs4 import BeautifulSoup
import re
import json

app = FastAPI()

BASE_DOMAIN = "https://narto-drama.com"
LIST_URL = f"{BASE_DOMAIN}/?lang=id-ID"

headers = {
    "User-Agent": "Mozilla/5.0"
}


# =========================
# SCRAPE LIST
# =========================
def scrape_list(url):
    resp = requests.get(url, headers=headers)
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
                "href": href,
            })

    return items


# =========================
# TOTAL EPISODE
# =========================
def get_total_episodes(url: str) -> int:
    resp = requests.get(url, headers=headers)
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


# =========================
# GET VIDEO URL
# =========================
def get_video_src_from_episode(url: str, ep: int):
    resp = requests.get(url, headers=headers)
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
    url = f"{BASE_DOMAIN}/search?lang=id-ID&q={q}"
    return scrape_list(url)


@app.get("/episodes")
def episodes(url: str):
    total = get_total_episodes(url)
    return {"total_episode": total}


@app.get("/video")
def video(url: str, ep: int = 1):
    video = get_video_src_from_episode(url, ep)
    return {"video_url": video}


# =========================
# VERCEL HANDLER (WAJIB)
# =========================
def handler(request, context):
    return app
