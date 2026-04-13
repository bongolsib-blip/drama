def scrape_list(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        items = []
        for card in soup.find_all("a", class_="card-link-overlay"):

            # 🔥 ambil title dari <h3>
            title_tag = card.find("h3")
            title = title_tag.get_text(strip=True) if title_tag else ""

            # href tetap dari <a>
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
