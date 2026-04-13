from http.server import BaseHTTPRequestHandler
import requests
import re
import json

BASE = "https://narto-drama.com"

headers = {
    "User-Agent": "Mozilla/5.0"
}


def clean_url(url: str) -> str:
    return url.replace("\\/", "/").replace("\\u0026", "&")


def get_video_url(slug: str, ep: int):
    try:
        watch_url = f"{BASE}/detail/watch/{slug}/{ep}?lang=id-ID"

        resp = requests.get(watch_url, headers=headers, timeout=10)
        html = resp.text

        # =========================
        # 🔥 ambil initialSourceUrl
        # =========================
        match = re.search(r'initialSourceUrl\s*=\s*"(.*?)"', html)

        if not match:
            return None

        raw_url = match.group(1)

        # clean encoding
        clean = clean_url(raw_url)

        return clean

    except Exception as e:
        return None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            path = self.path

            if path.startswith("/api/video"):
                query = path.split("?")[-1]
                params = dict(q.split("=") for q in query.split("&") if "=" in q)

                slug = params.get("slug")
                ep = int(params.get("ep", 1))

                if not slug:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error":"slug required"}')
                    return

                video_url = get_video_url(slug, ep)

                if not video_url:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'{"error":"video not found"}')
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()

                self.wfile.write(json.dumps({
                    "slug": slug,
                    "episode": ep,
                    "video_url": video_url
                }).encode())

            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"API OK")

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())
