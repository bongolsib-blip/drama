from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from mangum import Mangum
import requests
from bs4 import BeautifulSoup
import re
import json

app = FastAPI()
handler = Mangum(app)  # 🔥 penting

BASE_DOMAIN = "https://narto-drama.com"
LIST_URL = f"{BASE_DOMAIN}/?lang=id-ID"

headers = {
    "User-Agent": "Mozilla/5.0"
}


def scrape_list(url):
    resp = requests.get(url, headers=headers)
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
