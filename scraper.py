import json
import os
import sys

import requests

# ---- الإعدادات: كلها من متغيرات البيئة / GitHub Secrets ----
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
TMDB_API_KEY = os.environ["TMDB_API_KEY"]
TMDB_BASE = (os.environ.get("TMDB_BASE") or "https://api.themoviedb.org/3").rstrip("/")
LICENSED_FILE = os.environ.get("LICENSED_FILE") or "licensed_videos.json"

HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}


def upsert(table, rows, conflict):
    """upsert حقيقي: on_conflict ضروري، وإلا يفشل أو يكرر الصفوف."""
    if not rows:
        return
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={conflict}",
        json=rows,
        headers={**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
        timeout=30,
    )
    if r.status_code >= 300:
        print(f"فشل الكتابة في {table}: {r.status_code} {r.text}", file=sys.stderr)
        r.raise_for_status()


def sync_trending_movies():
    """1) أحدث الأفلام الرائجة من TMDB بكامل تفاصيلها."""
    r = requests.get(
        f"{TMDB_BASE}/trending/movie/week",
        params={"api_key": TMDB_API_KEY, "language": "ar"},
        timeout=15,
    )
    r.raise_for_status()
    rows = [
        {
            "tmdb_id": m["id"],
            "title": m.get("title") or m.get("original_title"),
            "original_title": m.get("original_title"),
            "overview": m.get("overview") or "",
            "poster_path": m.get("poster_path"),
            "type": "movie",
        }
        for m in r.json().get("results", [])
    ]
    upsert("movies", rows, "tmdb_id")
    print(f"تمت مزامنة {len(rows)} فيلم.")


def sync_trending_series():
    """2) أحدث المسلسلات الرائجة من TMDB بكامل تفاصيلها."""
    r = requests.get(
        f"{TMDB_BASE}/trending/tv/week",
        params={"api_key": TMDB_API_KEY, "language": "ar"},
        timeout=15,
    )
    r.raise_for_status()
    rows = []
    for s in r.json().get("results", []):
        series_name = s.get("name") or s.get("original_name") or "بدون عنوان"
        rows.append(
            {
                "tmdb_id": s["id"],
                "name": series_name,
                "title": series_name,
                "original_title": s.get("original_name"),
                "overview": s.get("overview") or "",
                "poster_path": s.get("poster_path"),
                "type": "tv",
            }
        )
    upsert("series", rows, "tmdb_id")
    print(f"تمت مزامنة {len(rows)} مسلسل.")


def sync_licensed_links():
    """3) روابط التشغيل: فقط من ملف لمحتوى تملكه أنت (MP4/M3U8 على استضافتك).
    شكل الملف: {"603": "https://your-cdn/603.m3u8", ...}
    """
    if not os.path.exists(LICENSED_FILE):
        print("لا يوجد ملف روابط مرخّصة، تم التخطي.")
        return
    with open(LICENSED_FILE, encoding="utf-8") as f:
        mapping = json.load(f)

    # تجاهل ما له رابط مسبقاً
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/video_links?select=tmdb_id",
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    existing = {row["tmdb_id"] for row in r.json()}

    rows = [
        {"tmdb_id": int(tid), "video_url": url, "type": "movie"}
        for tid, url in mapping.items()
        if int(tid) not in existing
    ]
    upsert("video_links", rows, "tmdb_id")
    print(f"أُضيف {len(rows)} رابط جديد.")


if __name__ == "__main__":
    failed = False
    for step_name, step_fn in [
        ("مزامنة الأفلام", sync_trending_movies),
        ("مزامنة المسلسلات", sync_trending_series),
        ("مزامنة الروابط", sync_licensed_links),
    ]:
        try:
            step_fn()
        except Exception as e:
            failed = True
            print(f"خطأ في {step_name}: {e}", file=sys.stderr)

    if failed:
        sys.exit(1)
