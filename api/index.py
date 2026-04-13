from fastapi import FastAPI, Query
from mangum import Mangum
import requests
from bs4 import BeautifulSoup
import re
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
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        return path.split("/")[-1] if path else ""
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
                    "href": href.split("?")[0],
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
# GET VIDEO PER EPISODE
# =========================
def get_video_src_from_episode(slug: str, ep: int):
    try:
        url = f"{BASE_DOMAIN}/detail/watch/{slug}/{ep}?lang=id-ID"
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code != 200:
            return None

        html = resp.text

        # ambil iframe / video source
        match = re.search(r'src="(https://[^"]+)"', html)

        if match:
            return match.group(1)

        return None

    except:
        return None


# =========================
# GET ALL VIDEO (LIMIT BIAR GAK TIMEOUT)
# =========================
def get_all_video_links(slug: str, max_ep: int):
    result = []

    # ⚠️ batasi biar tidak timeout di Vercel
    limit = min(max_ep, 20)

    for ep in range(1, limit + 1):
        video = get_video_src_from_episode(slug, ep)

        result.append({
            "episode": ep,
            "video_url": video
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

    video = get_video_src_from_episode(slug, ep)

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
    total = get_total_episodes(url)

    data = get_all_video_links(slug, total)

    return {
        "slug": slug,
        "total_episode": total,
        "fetched": len(data),
        "data": data
    }
