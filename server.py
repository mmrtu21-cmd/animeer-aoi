#!/usr/bin/env python3
"""АОИ: локальный сервер. Запуск:  python server.py   →  http://127.0.0.1:8000
В .env рядом положите строку:  KODIK_TOKEN=ваш_токен
"""
import json, os, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "aoi_anime_liquid_glass_kodik.html"
API = "https://kodik-api.com"
CACHE, TTL = {}, 300


def env():
    out = dict(os.environ)
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("\"'")
    return out


def token():
    e = env()
    return e.get("KODIK_TOKEN") or e.get("KODIK_API_KEY") or e.get("KODIK_API_TOKEN")


def kodik(path, **params):
    tk = token()
    if not tk:
        raise RuntimeError("Не найден KODIK_TOKEN в файле .env")
    params = {k: v for k, v in params.items() if v not in (None, "")}
    url = f"{API}/{path}?{urllib.parse.urlencode({**params, 'token': tk})}"
    hit = CACHE.get(url)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": "AOI/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    CACHE[url] = (time.time(), data)
    return data


def num(v):
    try:
        f = float(v)
        return round(f, 1) if f > 0 else None
    except (TypeError, ValueError):
        return None


def key_of(r):
    for prefix, f in (("s", "shikimori_id"), ("k", "kinopoisk_id"), ("i", "imdb_id")):
        if r.get(f):
            return prefix + str(r[f])
    return "x" + str(r.get("id"))


def card(r):
    m = r.get("material_data") or {}
    shots = m.get("screenshots") or []
    return {
        "key": key_of(r),
        "title": r.get("title") or m.get("title") or r.get("title_orig") or "Без названия",
        "orig": r.get("title_orig"),
        "year": r.get("year"),
        "poster": m.get("poster_url"),
        "banner": shots[0] if shots else None,
        "desc": m.get("anime_description") or m.get("description") or "",
        "genres": m.get("anime_genres") or m.get("all_genres") or m.get("genres") or [],
        "status": m.get("anime_status") or m.get("all_status"),
        "kp": num(m.get("kinopoisk_rating")),
        "imdb": num(m.get("imdb_rating")),
        "eps": m.get("episodes_total") or r.get("episodes_count"),
        "kind": r.get("type"),
    }


def unique(results, limit=36):
    seen = {}
    for r in results:
        c = card(r)
        old = seen.get(c["key"])
        if not old:
            seen[c["key"]] = c
        else:  # дополняем данными из записи, где они есть
            for k, v in c.items():
                if not old.get(k) and v:
                    old[k] = v
    return list(seen.values())[:limit]


COMMON = dict(types="anime-serial,anime", with_material_data="true", limit=100)


def catalog(q, mode):
    if q:
        data = kodik("search", title=q, **COMMON)
    elif mode == "ongoing":
        data = kodik("list", sort="updated_at", order="desc", anime_status="ongoing", **COMMON)
    else:
        data = kodik("list", sort="shikimori_rating", order="desc", has_field="kinopoisk_id", **COMMON)
    return {"items": unique(data.get("results", []))}


def title(key):
    field = {"s": "shikimori_id", "k": "kinopoisk_id", "i": "imdb_id", "x": "id"}.get(key[:1])
    if not field:
        raise RuntimeError("Неверный идентификатор")
    results = kodik("search", **{field: key[1:]}, with_material_data="true", limit=100).get("results", [])
    voices, seen = [], set()
    for r in results:
        t = r.get("translation") or {}
        if t.get("id") in seen or not r.get("link"):
            continue
        seen.add(t.get("id"))
        voices.append({"id": t.get("id"), "name": t.get("title") or "Озвучка", "type": t.get("type"),
                       "eps": r.get("episodes_count") or r.get("last_episode"),
                       "quality": r.get("quality"), "link": r["link"]})
    voices.sort(key=lambda v: (v["type"] == "subtitles", -(v["eps"] or 0)))
    best = next((r for r in results if r.get("material_data")), results[0] if results else None)
    return {"item": card(best) if best else None, "voices": voices}


class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/catalog":
                return self.send(200, catalog(q.get("q", "").strip(), q.get("mode", "popular")))
            if u.path == "/api/title":
                return self.send(200, title(q.get("key", "")))
            self.send(404, {"detail": "Не найдено"})
        except Exception as e:  # noqa: BLE001
            self.send(502, {"detail": f"Kodik: {e}"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("АОИ запущен: http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), H).serve_forever()
