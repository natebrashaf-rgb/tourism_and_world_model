# -*- coding: utf-8 -*-
"""
三语文旅文献爬虫（OpenAlex）——概念时序实验 Day1 数据源

功能:
    按语言(zh/en/ar)与年份, 用文旅主题词表做 title_and_abstract 过滤,
    抓取精简字段并按 OpenAlex id 去重, 写出 data_v2/<lang>/works.jsonl。
    不含中阿打分/机构路; 供 build_concept_panel.py 构建概念面板。

依赖: pip install requests
环境变量: OPENALEX_API_KEY (可选, 匿名易 429)
用法:
    python fetch_tourism_ml.py --lang zh --year-from 2024 --year-to 2024 --per-year 50
    python fetch_tourism_ml.py --lang ar --year-from 2010 --year-to 2025 --per-year 0
    python fetch_tourism_ml.py --lang en --year-from 2010 --year-to 2025 --per-year 3000
"""

import argparse
import json
import os
import sys
import time

import requests

BASE = "https://api.openalex.org"
SELECT_FIELDS = ",".join([
    "id", "doi", "display_name", "publication_year", "language",
    "type", "cited_by_count", "abstract_inverted_index",
    "keywords", "topics",
])

# ---------------------------------------------------------------- 词表配置 --
TOURISM_ZH = [
    "旅游", "文旅", "文化旅游", "文化", "文化遗产", "非物质文化遗产",
    "博物馆", "文物", "考古", "遗址", "古镇", "乡村旅游",
    "酒店", "民宿", "景区", "旅行", "游客", "观光", "度假",
    "文创", "演艺", "研学",
]

TOURISM_EN = [
    "tourism", "tourist", "tourists", "travel", "hospitality",
    "cultural", "culture", "heritage", "museum", "archaeological",
    "leisure", "hotel", "hotels", "tourism industry", "destination",
]

TOURISM_AR = [
    "السياحة", "سياحة", "سياحية", "سياحي", "السياحي", "سياح",
    "الثقاف", "ثقاف", "الثقافية", "ثقافة",
    "التراث", "تراث", "تراثية", "التراثية",
    "الضيافة", "ضيافة",
    "المتاحف", "متحف", "الأثرية", "أثرية", "أثري",
    "المعالم", "الفنادق", "فنادق",
]

WORDLISTS = {"zh": TOURISM_ZH, "en": TOURISM_EN, "ar": TOURISM_AR}
DEFAULT_DELAY = {"zh": 0.12, "en": 0.15, "ar": 0.12}


def or_terms(terms):
    return " OR ".join(terms)


def decode_abstract(inverted):
    if not inverted:
        return ""
    pos = []
    for word, idxs in inverted.items():
        for i in idxs:
            pos.append((i, word))
    pos.sort()
    return " ".join(w for _, w in pos)


def slim_record(w):
    """压成实验所需精简记录; keywords/topics 只留 id 与显示名。"""
    kws = []
    for k in w.get("keywords") or []:
        kid = (k.get("id") or "").rsplit("/", 1)[-1]
        if kid:
            kws.append({"id": kid, "name": k.get("display_name") or kid})
    tops = []
    for t in w.get("topics") or []:
        tid = t.get("id") or ""
        # 形如 https://openalex.org/topics/T10739 → T10739
        tid = tid.rsplit("/", 1)[-1]
        if tid:
            tops.append({"id": tid, "name": t.get("display_name") or tid})
    return {
        "id": (w.get("id") or "").rsplit("/", 1)[-1],
        "doi": w.get("doi") or "",
        "title": w.get("display_name") or "",
        "abstract": decode_abstract(w.get("abstract_inverted_index")),
        "year": w.get("publication_year"),
        "language": w.get("language"),
        "type": w.get("type"),
        "cited_by_count": w.get("cited_by_count"),
        "keywords": kws,
        "topics": tops,
    }


class OpenAlexClient:
    # key/mailto 鉴权 + 429/5xx 重试 + 限速
    def __init__(self, api_key=None, mailto="research@example.com", delay=0.12):
        self.api_key = api_key or os.environ.get("OPENALEX_API_KEY") or ""
        self.mailto = mailto
        self.delay = delay
        self.session = requests.Session()
        self.requests_made = 0

    def _params(self, extra):
        p = dict(extra)
        if self.api_key:
            p["api_key"] = self.api_key
        elif self.mailto:
            p["mailto"] = self.mailto
        return p

    def get(self, path, params, retries=6):
        url = f"{BASE}{path}"
        params = self._params(params)
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=60)
            except requests.RequestException:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
                continue
            self.requests_made += 1
            if r.status_code == 429:
                retry_after = float(r.headers.get("Retry-After") or (2 ** attempt))
                print(f"    [429] 等待 {retry_after:.0f}s ({attempt + 1}/{retries})", flush=True)
                time.sleep(retry_after + 0.5)
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            time.sleep(self.delay)
            return r.json()
        raise RuntimeError(f"重试耗尽: {url}")

    def count(self, filt):
        data = self.get("/works", {"filter": filt, "per_page": 1, "select": "id"})
        return data["meta"]["count"]

    def iterate(self, filt, per_page=200, max_results=None):
        # cursor 分页迭代
        cursor = "*"
        fetched = 0
        while cursor:
            params = {
                "filter": filt,
                "per_page": per_page,
                "cursor": cursor,
                "select": SELECT_FIELDS,
            }
            data = self.get("/works", params)
            results = data.get("results") or []
            for w in results:
                yield w
                fetched += 1
                if max_results and fetched >= max_results:
                    return
            cursor = (data.get("meta") or {}).get("next_cursor")
            if not cursor or not results:
                return


def year_filter(y):
    return f",from_publication_date:{y}-01-01,to_publication_date:{y}-12-31"


def fetch_year(client, lang, y, per_year):
    terms = or_terms(WORDLISTS[lang])
    filt = f"language:{lang},title_and_abstract.search:{terms}{year_filter(y)}"
    limit = per_year if per_year and per_year > 0 else None
    rows = []
    seen = set()
    for w in client.iterate(filt, max_results=limit):
        wid = (w.get("id") or "").rsplit("/", 1)[-1]
        if not wid or wid in seen:
            continue
        seen.add(wid)
        rec = slim_record(w)
        if not rec["title"]:
            continue
        rec["_fetch_year"] = y
        rows.append(rec)
    return filt, rows


def main():
    ap = argparse.ArgumentParser(description="三语文旅 OpenAlex 爬虫")
    ap.add_argument("--lang", required=True, choices=["zh", "en", "ar"])
    ap.add_argument("--year-from", type=int, default=2010)
    ap.add_argument("--year-to", type=int, default=2025)
    ap.add_argument("--per-year", type=int, default=0, help="每年上限, 0=不截断")
    ap.add_argument("--out-dir", default="data_v2")
    ap.add_argument("--delay", type=float, default=None)
    ap.add_argument("--resume", action="store_true",
                    help="已存在的 id 跳过(按年文件已写则跳年)")
    args = ap.parse_args()

    lang = args.lang
    out_root = os.path.join(args.out_dir, lang)
    os.makedirs(out_root, exist_ok=True)
    out_path = os.path.join(out_root, "works.jsonl")

    delay = args.delay if args.delay is not None else DEFAULT_DELAY[lang]
    client = OpenAlexClient(delay=delay)
    key_src = "API key" if client.api_key else "匿名(mailto)"
    print(f"lang={lang} years={args.year_from}-{args.year_to} "
          f"per_year={args.per_year or 'ALL'} client={key_src}", flush=True)

    # 已抓 id：支持跨次续跑
    seen_ids = set()
    if args.resume and os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    seen_ids.add(json.loads(line)["id"])
                except Exception:
                    pass
        print(f"resume: 已载入 {len(seen_ids)} 条 id", flush=True)

    mode = "a" if args.resume else "w"
    new_total = 0
    with open(out_path, mode, encoding="utf-8") as f:
        for y in range(args.year_from, args.year_to + 1):
            try:
                filt, rows = fetch_year(client, lang, y, args.per_year)
            except Exception as e:
                print(f"  [{lang} {y}] 失败: {e}", flush=True)
                continue
            wrote = 0
            for rec in rows:
                if rec["id"] in seen_ids:
                    continue
                seen_ids.add(rec["id"])
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                wrote += 1
                new_total += 1
            f.flush()
            print(f"  [{lang} {y}] 唯一新写 {wrote} (本年抓 {len(rows)}), "
                  f"累计 id={len(seen_ids)}, req={client.requests_made}", flush=True)

    print(f"\n完成 {lang}: 新增 {new_total}, 文件 {out_path}, "
          f"总 id={len(seen_ids)}, 请求数={client.requests_made}", flush=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
