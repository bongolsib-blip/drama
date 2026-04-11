import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse, urlencode

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
# MAIN HANDLER (Vercel)
# =========================
def handler(request):
    path = request.path

    try:
        # Endpoint: /api/list
        if path.endswith("/list"):
            items = scrape_list(LIST_URL)
            return {
                "statusCode": 200,
                "body": json.dumps(items)
            }

        # Endpoint: /api/search?q=keyword
        elif path.endswith("/search"):
            query = request.args.get("q", "")
            search_url = f"{BASE_DOMAIN}/search?lang=id-ID&q={query}"
            items = scrape_list(search_url)

            return {
                "statusCode": 200,
                "body": json.dumps(items)
            }

        # Endpoint: /api/episodes?url=...
        elif path.endswith("/episodes"):
            url = request.args.get("url")
            total = get_total_episodes(url)

            return {
                "statusCode": 200,
                "body": json.dumps({"total_episode": total})
            }

        # Endpoint: /api/video?url=...&ep=1
        elif path.endswith("/video"):
            url = request.args.get("url")
            ep = int(request.args.get("ep", 1))

            video = get_video_src_from_episode(url, ep)

            return {
                "statusCode": 200,
                "body": json.dumps({"video_url": video})
            }

        else:
            return {
                "statusCode": 404,
                "body": "Not Found"
            }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }