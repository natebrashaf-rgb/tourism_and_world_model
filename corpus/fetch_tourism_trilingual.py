# -*- coding: utf-8 -*-
"""
文旅三语文献抓取（OpenAlex）

按语种独立召回，不要求中阿双边。
依赖: pip install requests
环境变量: OPENALEX_API_KEY（推荐）

用法:
    python fetch_tourism_trilingual.py --lang en --out data_en --max 4000
    python fetch_tourism_trilingual.py --lang zh --out data_zh --max 4000
    python fetch_tourism_trilingual.py --lang ar --out data_ar --max 4000
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests  # pyright: ignore[reportMissingModuleSource]

OA = "https://api.openalex.org"
SELECT = ",".join([
    "id", "doi", "display_name", "title", "publication_year", "type",
    "language", "cited_by_count", "is_retracted", "abstract_inverted_index",
    "primary_location", "authorships", "keywords", "topics",
])
KEEP_TYPES = {
    "article", "review", "book-chapter", "book", "proceedings-article",
    "dissertation", "report",
}
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def load_keywords(path, lang):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data[lang]


def decode_abstract(inverted):
    if not inverted:
        return ""
    pos = []
    for word, idxs in inverted.items():
        for i in idxs:
            pos.append((i, word))
    pos.sort()
    return " ".join(w for _, w in pos)


def arabic_ratio(text):
    letters = [c for c in (text or "") if c.isalpha() or ("\u0600" <= c <= "\u06FF")]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "\u0600" <= c <= "\u06FF") / len(letters)


def hits_topic(title, abstract, kws):
    blob = ((title or "") + " " + (abstract or "")).lower()
    return [k for k in kws if k.lower() in blob]


def flatten(w, lang, query, topic_hits):
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    authors = []
    for a in w.get("authorships") or []:
        authors.append(a.get("raw_author_name") or (a.get("author") or {}).get("display_name") or "")
    return {
        "id": (w.get("id") or "").rsplit("/", 1)[-1],
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "title": w.get("display_name") or w.get("title") or "",
        "abstract": decode_abstract(w.get("abstract_inverted_index")),
        "year": w.get("publication_year"),
        "type": w.get("type"),
        "language": lang,
        "cited_by_count": w.get("cited_by_count") or 0,
        "venue": src.get("display_name") or "",
        "authors": "; ".join(a for a in authors if a),
        "topic_hits": topic_hits,
        "crawl_query": query,
        "source_db": "openalex",
    }


def oa_get(session, params, api_key, mailto, retries=6):
    if api_key:
        params["api_key"] = api_key
    elif mailto:
        params["mailto"] = mailto
    last = None
    for attempt in range(retries):
        try:
            r = session.get(OA + "/works", params=params, timeout=60)
        except requests.RequestException as e:  # 网络抖动
            last = e
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429:
            # OpenAlex 匿名池会返回夸张的 Retry-After（曾见 55324s），不能当真：
            # 单次请求可成功 → 只做短退避重试，不要直接判定"额度耗尽"。
            hinted = float(r.headers.get("Retry-After") or 0)
            wait = min(max(hinted, 2 ** attempt), 45)
            print("    429 退避 %.0fs (第%s次) 服务端提示=%.0fs" % (wait, attempt + 1, hinted), flush=True)
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("OpenAlex 重试耗尽: %s" % last)


def iterate(session, filt, search, api_key, mailto, delay, max_results):
    cursor = "*"
    fetched = 0
    while cursor:
        params = {"filter": filt, "search": search, "per_page": 200,
                  "cursor": cursor, "select": SELECT}
        data = oa_get(session, params, api_key, mailto)
        results = data.get("results") or []
        for w in results:
            yield w
            fetched += 1
            if max_results and fetched >= max_results:
                return
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not cursor or not results:
            return
        time.sleep(delay)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=["en", "zh", "ar"])
    ap.add_argument("--out", default="data")
    ap.add_argument("--max", type=int, default=4000)
    ap.add_argument("--year-from", default="2010")
    ap.add_argument("--year-to", default="2024")
    ap.add_argument("--delay", type=float, default=0.12)
    ap.add_argument("--mailto", default="research@bisu.edu.cn")
    ap.add_argument("--keywords", default="keywords.json")
    args = ap.parse_args()

    kws = load_keywords(args.keywords, args.lang)
    os.makedirs(args.out, exist_ok=True)
    api_key = os.environ.get("OPENALEX_API_KEY") or ""
    session = requests.Session()
    filt = "language:%s,is_retracted:false,from_publication_date:%s-01-01,to_publication_date:%s-12-31" % (
        args.lang, args.year_from, args.year_to,
    )

    seen, recs = set(), []
    print("lang=%s queries=%s max=%s" % (args.lang, len(kws), args.max), flush=True)
    for qi, q in enumerate(kws, 1):
        if len(recs) >= args.max:
            break
        got = 0
        try:
            for w in iterate(session, filt, q, api_key, args.mailto, args.delay, None):
                if len(recs) >= args.max:
                    break
                title = w.get("display_name") or w.get("title") or ""
                if len(title.strip()) < 8:
                    continue
                if w.get("type") and w.get("type") not in KEEP_TYPES:
                    continue
                abstract = decode_abstract(w.get("abstract_inverted_index"))
                if args.lang == "ar":
                    if not ARABIC_RE.search(title) or arabic_ratio(title + " " + abstract) < 0.15:
                        continue
                topic = hits_topic(title, abstract, kws)
                if not topic:
                    continue
                key = (w.get("doi") or "").lower() or (w.get("id") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                recs.append(flatten(w, args.lang, q, topic))
                got += 1
        except Exception as e:
            print("  [%s/%s] fail %s (%s)" % (qi, len(kws), q, e), flush=True)
            if "额度耗尽" in str(e):
                break
            continue
        print("  [%s/%s] +%s total=%s | %s" % (qi, len(kws), got, len(recs), q), flush=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(args.out, "works_%s_%s.jsonl" % (args.lang, ts))
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("wrote %s (%s)" % (path, len(recs)))


if __name__ == "__main__":
    _reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")  # pyright: ignore[reportAttributeAccessIssue]
    main()
