import json
import re
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import Flask, Response, abort, render_template

app = Flask(__name__)

INSTAGRAM_USERNAME = "psi.nayararocha"
INSTAGRAM_PROFILE_URL = f"https://www.instagram.com/{INSTAGRAM_USERNAME}/"
INSTAGRAM_API_URL = (
    "https://i.instagram.com/api/v1/users/web_profile_info/"
    f"?username={INSTAGRAM_USERNAME}"
)
INSTAGRAM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "x-ig-app-id": "936619743392459",
    "Accept": "application/json",
}

# Cache em memória
# Observação: na Vercel esse cache pode não persistir entre execuções,
# porque o ambiente é serverless. Ainda assim, mantemos como fallback.
INSTAGRAM_CACHE_TTL = 1800  # 30 minutos
INSTAGRAM_CACHE = {"timestamp": 0.0, "data": None}


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _build_fallback_instagram_data():
    return {
        "username": INSTAGRAM_USERNAME,
        "profile_url": INSTAGRAM_PROFILE_URL,
        "full_name": "Nayara Rocha",
        "biography": "",
        "followers": 0,
        "posts": [],
    }


def _extract_caption(node):
    caption_edges = (
        node.get("edge_media_to_caption", {}).get("edges", [])
        if isinstance(node, dict)
        else []
    )
    if not caption_edges:
        return "Ver publicação no Instagram."

    edge_node = (
        caption_edges[0].get("node", {})
        if isinstance(caption_edges[0], dict)
        else {}
    )
    text = edge_node.get("text", "") if isinstance(edge_node, dict) else ""
    return (text or "Ver publicação no Instagram.").strip()


def _fetch_instagram_data(limit=6):
    req = Request(INSTAGRAM_API_URL, headers=INSTAGRAM_HEADERS)
    with urlopen(req, timeout=10) as response:
        raw = response.read().decode("utf-8")

    payload = json.loads(raw)
    user = payload.get("data", {}).get("user", {})

    posts = []
    timeline = user.get("edge_owner_to_timeline_media", {})

    for edge in timeline.get("edges", [])[:limit]:
        node = edge.get("node", {}) if isinstance(edge, dict) else {}
        shortcode = node.get("shortcode", "")
        image_url = node.get("thumbnail_src") or node.get("display_url")

        if not shortcode or not image_url:
            continue

        posts.append(
            {
                "url": f"https://www.instagram.com/p/{shortcode}/",
                "shortcode": shortcode,
                "image": image_url,
                "caption": _extract_caption(node),
                "is_video": bool(node.get("is_video", False)),
            }
        )

    return {
        "username": user.get("username", INSTAGRAM_USERNAME),
        "profile_url": INSTAGRAM_PROFILE_URL,
        "full_name": user.get("full_name", "Nayara Rocha"),
        "biography": user.get("biography", ""),
        "followers": _safe_int(user.get("edge_followed_by", {}).get("count")),
        "posts": posts,
    }


def get_instagram_data(limit=6):
    now = time.time()
    cached = INSTAGRAM_CACHE.get("data")

    if cached and now - INSTAGRAM_CACHE["timestamp"] < INSTAGRAM_CACHE_TTL:
        return cached

    try:
        fresh_data = _fetch_instagram_data(limit=limit)
        INSTAGRAM_CACHE["timestamp"] = now
        INSTAGRAM_CACHE["data"] = fresh_data
        return fresh_data
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError):
        if cached:
            return cached
        return _build_fallback_instagram_data()


@app.route("/")
def home():
    instagram = get_instagram_data(limit=6)
    return render_template("index.html", instagram=instagram)


@app.route("/instagram/thumb/<shortcode>")
def instagram_thumb(shortcode):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", shortcode):
        abort(404)

    instagram = get_instagram_data(limit=18)
    image_url = next(
        (
            post.get("image")
            for post in instagram.get("posts", [])
            if post.get("shortcode") == shortcode
        ),
        None,
    )

    if not image_url:
        abort(404)

    request_headers = {
        "User-Agent": INSTAGRAM_HEADERS["User-Agent"],
        "Referer": INSTAGRAM_PROFILE_URL,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    try:
        request = Request(image_url, headers=request_headers)
        with urlopen(request, timeout=12) as response:
            image_bytes = response.read()
            content_type = response.headers.get("Content-Type", "image/jpeg")
    except URLError:
        abort(502)

    proxy_response = Response(image_bytes, mimetype=content_type)
    proxy_response.headers["Cache-Control"] = "public, max-age=1800"
    return proxy_response


# Isso garante que a Vercel consiga expor sua aplicação Flask
app = app

if __name__ == "__main__":
    app.run(debug=True)