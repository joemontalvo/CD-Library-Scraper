#!/usr/bin/env python3
"""
Fetch all Music CDs from the Yorba Linda Public Library catalog (BiblioCommons)
and write them to data/music_cds.json.

Designed to run in a GitHub Action, but also works locally:
    python3 fetch_cds.py            # normal run
    python3 fetch_cds.py --debug    # also saves data/raw_page1.json for inspection

Needs Python 3.8+ and no extra packages.

NOTE: Uses BiblioCommons' unofficial JSON "gateway" API. It was written from the
API's usual structure and has not been tested against YLPL, so fields are read
defensively. If the run fails or fields come back blank, run with --debug and
check data/raw_page1.json.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

LIBRARY = "ylpl"
QUERY = "formatcode:(MUSIC_CD )"   # add filters here, e.g. formatcode:(MUSIC_CD ) audience:"adult"
SORT = "newly_acquired"            # or: title, author, relevancy
LIMIT = 100                        # items per request
DELAY = 1.5                        # seconds between requests (be gentle)
OUT_DIR = "data"
OUT_FILE = os.path.join(OUT_DIR, "music_cds.json")

BASE = f"https://gateway.bibliocommons.com/v2/libraries/{LIBRARY}/bibs/search"
CATALOG = f"https://{LIBRARY}.bibliocommons.com"
DEBUG = "--debug" in sys.argv


def fetch_page(page, retries=3):
    params = {
        "query": QUERY,
        "searchType": "bl",
        "sort": SORT,
        "limit": LIMIT,
        "page": page,
        "suppress": "true",
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (personal library catalog viewer)",
        "Accept": "application/json",
    })
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", "n/a")
            print(f"  page {page}, attempt {attempt} failed (HTTP {code}): {e}", file=sys.stderr)
            if attempt == retries:
                raise
            time.sleep(5 * attempt)


def pick(d, *keys, default=""):
    """Return the first non-empty value among keys in dict d."""
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, "", []):
            return d[k]
    return default


def parse(data):
    bibs = data.get("entities", {}).get("bibs", {})
    results = data.get("catalogSearch", {}).get("results", [])
    ids = []
    for r in results:
        bid = r if isinstance(r, str) else (r.get("representative") or r.get("id"))
        if bid:
            ids.append(bid)

    items = []
    for bid in ids:
        b = bibs.get(bid)
        if not b:
            continue
        info = b.get("briefInfo", {})
        avail = b.get("availability", {})
        jacket = info.get("jacket") or {}
        authors = info.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        items.append({
            "id": bid,
            "title": pick(info, "title"),
            "subtitle": pick(info, "subtitle"),
            "artist": ", ".join(authors),
            "year": str(pick(info, "publicationDate")),
            "callNumber": pick(info, "callNumber"),
            "cover": pick(jacket, "medium", "large", "small"),
            "status": pick(avail, "localisedStatus", "status", default="Unknown"),
            "available": pick(avail, "availableCopies", default=0),
            "total": pick(avail, "totalCopies", default=0),
            "url": f"{CATALOG}/v2/record/{bid}",
        })
    pages = data.get("catalogSearch", {}).get("pagination", {}).get("pages", 1) or 1
    return items, pages


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    seen, items_all = set(), []
    page, pages = 1, 1
    while page <= pages:
        print(f"Fetching page {page} of {pages}...", flush=True)
        data = fetch_page(page)
        if DEBUG and page == 1:
            with open(os.path.join(OUT_DIR, "raw_page1.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        items, pages = parse(data)
        for it in items:
            if it["id"] not in seen:
                seen.add(it["id"])
                items_all.append(it)
        page += 1
        if page <= pages:
            time.sleep(DELAY)

    # Safety: never overwrite good data with an empty result.
    if not items_all:
        print("ERROR: no items parsed. Not overwriting existing data. "
              "Run with --debug and inspect data/raw_page1.json.", file=sys.stderr)
        sys.exit(1)

    out = {
        "library": LIBRARY,
        "query": QUERY,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(items_all),
        "items": items_all,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Wrote {len(items_all)} CDs to {OUT_FILE}")


if __name__ == "__main__":
    main()
