#!/usr/bin/env python3
"""AOI: раздаёт index.html и проксирует поиск Kodik (токен остаётся на сервере)."""
import json, os, time, urllib.parse, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).parent
KODIK_HOSTS = ["https://kodik-api.com"]  # kodikapi.com и kodik.biz больше не работают
CACHE, CACHE_TTL = {}, 600  # секунд


def load_env():
    f = BASE / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))


def load_tokens():
    """Порядок: KODIK_TOKEN из .env, затем stable -> unstable -> legacy из tokens.json."""
    tokens = []
    if os.environ.get("KODIK_TOKEN"):
        tokens.append(os.environ["KODIK_TOKEN"])
    f = BASE / "tokens.json"
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        for group in ("stable", "unstable"):
            for t in data.get(group, []):
                if t.get("functions_availability", {}).get("search") and t["tokn"] not in tokens:
                    tokens.append(t["tokn"])
    return tokens


def kodik_search(query):
    errors = []
    for token in load_tokens():
        params = urllib.parse.urlencode({
            "token": token, "title": query, "types": "anime,anime-serial",
            "with_material_data": "true", "limit": 50,
        })
        for host in KODIK_HOSTS:
            try:
                req = urllib.request.Request(f"{host}/search?{params}", headers={"User-Agent": "Mozilla/5.0 AOI/1.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.load(r)
            except urllib.error.HTTPError as e:
                body = e.read()[:200].decode("utf-8", "replace")
                errors.append(f"{token[:6]}…: HTTP {e.code} {body}"); continue
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                errors.append(f"{host}: {e}"); continue
            if data.get("error"):
                errors.append(f"{token[:6]}…: {data['error']}"); continue
            return data.get("results", [])
    raise RuntimeError(" | ".join(errors) or "Нет токенов (KODIK_TOKEN / tokens.json)")


def normalize(results):
    out, seen = [], set()
    for r in results:
        link = r.get("link")
        if not link:
            continue
        tr = (r.get("translation") or {}).get("title")
        key = (r.get("id") or link)
        if key in seen:
            continue
        seen.add(key)
        title = r.get("title") or r.get("title_orig") or "Без названия"
        out.append({
            "title": f"{title} — {tr}" if tr else title,
            "type": r.get("type", "anime"),
            "year": r.get("year"),
            "link": link,
        })
    return out[:20]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self._send(200, (BASE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/kodik/search":
            q = urllib.parse.parse_qs(url.query).get("q", [""])[0].strip()
            if not q:
                return self._send(400, json.dumps({"detail": "Пустой запрос"}))
            hit = CACHE.get(q.lower())
            if hit and time.time() - hit[0] < CACHE_TTL:
                return self._send(200, json.dumps({"results": hit[1]}))
            try:
                results = normalize(kodik_search(q))
            except RuntimeError as e:
                return self._send(502, json.dumps({"detail": f"Kodik API недоступен: {e}"}))
            CACHE[q.lower()] = (time.time(), results)
            return self._send(200, json.dumps({"results": results}))
        self._send(404, json.dumps({"detail": "Not found"}))  # tokens.json и .env НЕ раздаются

    def log_message(self, fmt, *a):
        pass


if __name__ == "__main__":
    load_env()
    port = int(os.environ.get("PORT", 8000))
    print(f"Токенов найдено: {len(load_tokens())}")
    print(f"AOI: http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
