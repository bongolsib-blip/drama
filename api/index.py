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
            return {
                "error": "initialSourceUrl not found",
                "debug_html_snippet": html[:500]  # potong biar ringan
            }

        raw_url = match.group(1)

        # DEBUG sebelum clean
        debug_raw = raw_url

        # clean encoding
        clean = clean_url(raw_url)

        return {
            "raw": debug_raw,
            "clean": clean
        }

    except Exception as e:
        return {
            "error": str(e)
        }


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

                result = get_video_url(slug, ep)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()

                self.wfile.write(json.dumps(result, indent=2).encode())

            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"API OK")

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())
