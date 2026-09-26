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
from urllib.parse import urlencode

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

# 收窄词表（--wordlist strict）
# 动因：全量词表里的宽泛词把非文旅文献大量带进来。实测严格文旅词命中率
# （见 validate_corpus.py 报告项）：en 62.2% / zh 41.3% / ar 22.8%。
# 祸首是单独成词的 "文化"、"ثقاف"、"culture / travel / leisure" 这类——
# 它们在学术写作里太常见，等于用"文化"当检索词。
# strict 只保留"一眼是文旅"的词，但保留短语（cultural heritage 等）不砍。
TOURISM_ZH_STRICT = [
    "旅游", "文旅", "旅游业", "文化旅游", "遗产旅游", "生态旅游",
    "乡村旅游", "红色旅游", "工业旅游", "研学旅行",
    "博物馆", "非物质文化遗产", "旅游景区", "旅游产业", "游客",
    "民宿", "旅游目的地",
]

TOURISM_EN_STRICT = [
    "tourism", "tourist", "tourists", "destination", "destinations",
    "hospitality", "museum", "museums", "pilgrimage", "ecotourism",
    "heritage",
]
# 注意：这里**不能**放多词短语或带连字符的词。
# OpenAlex 的 title_and_abstract.search 不做短语匹配，会把 "tourist attraction"
# 拆成 tourist/attraction、"eco-tourism" 拆成 eco/tourism，
# 于是 "Level attraction in circuit electromechanics"、"Building an Eco-Innovation
# Cluster" 全被召回——实测短语版 EN 语料里 45% 不含任何核心旅游词。

TOURISM_AR_STRICT = [
    "السياحة", "سياحة", "سياحي", "سياحية", "السياحي", "سياح",
    "السياحة الثقافية", "السياحة الدينية", "التراث السياحي",
    "الضيافة", "ضيافة",
    "المتاحف", "متحف",
    "الفنادق", "فنادق",
    "الحج", "العمرة", "المزارات السياحية",
]

WORDLISTS_STRICT = {"zh": TOURISM_ZH_STRICT, "en": TOURISM_EN_STRICT,
                    "ar": TOURISM_AR_STRICT}
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
    # transport="direct" 直连 api.openalex.org
    # transport="jina"   经 r.jina.ai 中转（换出口 IP；本机 IP 的匿名池已被
    #                    OpenAlex 整体 429，见 exp/NOTES.md）
    def __init__(self, api_key=None, mailto="research@bisu.edu.cn", delay=0.12,
                 transport="direct"):
        self.api_key = api_key or os.environ.get("OPENALEX_API_KEY") or ""
        self.mailto = mailto
        self.delay = delay
        self.transport = transport
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "TourismResearchBot/1.0 (mailto:research@bisu.edu.cn)",
            "Accept": "application/json",
        })
        self.requests_made = 0

    def _params(self, extra):
        p = dict(extra)
        if self.api_key:
            p["api_key"] = self.api_key
        elif self.mailto:
            p["mailto"] = self.mailto
        return p

    def _fetch(self, url, params):
        """返回 (status, json|None, retry_after)。"""
        if self.transport == "jina":
            full = url + "?" + urlencode(params)
            # Accept 必须显式改成 text/plain：会话默认的 application/json 会让
            # r.jina.ai 包一层 {"code":..,"data":{"content":"..."}} 信封，直接解析会拿到 0 条。
            r = self.session.get("https://r.jina.ai/" + full,
                                 headers={"x-return-format": "text",
                                          "Accept": "text/plain"},
                                 timeout=180)
            self.requests_made += 1
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    return 502, None, None
                if isinstance(data, dict) and "results" not in data and "meta" not in data:
                    # 识别 jina/上游的错误信封，不要当成"空结果"
                    return 502, None, None
                return 200, data, None
            return r.status_code, None, r.headers.get("Retry-After")
        r = self.session.get(url, params=params, timeout=60)
        self.requests_made += 1
        if r.status_code == 200:
            return 200, r.json(), None
        return r.status_code, None, r.headers.get("Retry-After")

    def get(self, path, params, retries=6):
        url = f"{BASE}{path}"
        params = self._params(params)
        base_wait = 20 if self.transport == "jina" else 5
        for attempt in range(retries):
            try:
                status, data, retry_after = self._fetch(url, params)
            except requests.RequestException:
                if attempt == retries - 1:
                    raise
                time.sleep(base_wait * (attempt + 1))
                continue
            if status == 429:
                # 服务端 Retry-After 是假值（曾见 52000s），忽略，只做递增退避
                wait = min(base_wait * (2 ** attempt), 120)
                print(f"    [429] 等待 {wait:.0f}s ({attempt + 1}/{retries}) "
                      f"服务端提示={retry_after}", flush=True)
                time.sleep(wait)
                continue
            if status >= 500:
                time.sleep(base_wait * (attempt + 1))
                continue
            if status >= 400:
                raise RuntimeError(f"HTTP {status}: {str(data)[:200]}")
            time.sleep(self.delay)
            return data
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


def fetch_year(client, lang, y, per_year, wordlists=None):
    wl = wordlists or WORDLISTS
    terms = or_terms(wl[lang])
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
    ap.add_argument("--transport", choices=["direct", "jina"], default="direct",
                    help="direct=直连 OpenAlex；jina=经 r.jina.ai 中转换出口 IP")
    ap.add_argument("--wordlist", choices=["full", "strict"], default="full",
                    help="full=PLAN.md 原词表；strict=收窄词表（去掉过宽单字词）")
    args = ap.parse_args()

    lang = args.lang
    out_root = os.path.join(args.out_dir, lang)
    os.makedirs(out_root, exist_ok=True)
    out_path = os.path.join(out_root, "works.jsonl")

    wordlists = WORDLISTS_STRICT if args.wordlist == "strict" else WORDLISTS
    delay = args.delay if args.delay is not None else DEFAULT_DELAY[lang]
    client = OpenAlexClient(delay=delay, transport=args.transport)
    key_src = "API key" if client.api_key else "匿名(mailto)"
    print(f"lang={lang} years={args.year_from}-{args.year_to} "
          f"per_year={args.per_year or 'ALL'} client={key_src} "
          f"transport={args.transport} wordlist={args.wordlist}"
          f"({len(wordlists[lang])} 词)", flush=True)

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
                filt, rows = fetch_year(client, lang, y, args.per_year, wordlists)
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
