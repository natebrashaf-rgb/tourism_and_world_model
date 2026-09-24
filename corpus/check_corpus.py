# -*- coding: utf-8 -*-
"""
语料体检：读 corpus/data_<lang>/works_*.jsonl，输出规模 / 年份分布 / 命中词 / 类型 / 期刊 / 抽样标题。

用法:
    /usr/bin/python3 check_corpus.py            # 体检全部语种
    /usr/bin/python3 check_corpus.py en zh      # 指定语种
"""

import glob
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))


def load(lang):
    paths = sorted(glob.glob(os.path.join(HERE, "data_%s" % lang, "works_*.jsonl")))
    if not paths:
        return None, []
    recs, seen = [], set()
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                key = (r.get("doi") or "").lower() or r.get("id")
                if key in seen:
                    continue
                seen.add(key)
                recs.append(r)
    return paths, recs


def report(lang):
    paths, recs = load(lang)
    print("=" * 60)
    if not recs:
        print("[%s] 无数据（data_%s/ 为空）" % (lang, lang))
        return None
    print("[%s] 文件 %s" % (lang, [os.path.basename(p) for p in paths]))
    print("[%s] 有效记录 %d 条" % (lang, len(recs)))

    years = Counter(r.get("year") for r in recs)
    span = sorted(y for y in years if isinstance(y, int)) or [0]
    print("[%s] 年份 %s-%s" % (lang, span[0], span[-1]))
    print("     年份分布: " + " ".join("%d:%d" % (y, years[y]) for y in span))

    types = Counter(r.get("type") for r in recs)
    print("     类型: " + ", ".join("%s=%d" % kv for kv in types.most_common()))

    langs = Counter(r.get("language") for r in recs)
    print("     标注语种: " + ", ".join("%s=%d" % kv for kv in langs.most_common()))

    hits = Counter()
    multi = 0
    for r in recs:
        hs = r.get("topic_hits") or []
        if len(hs) > 1:
            multi += 1
        for h in hs:
            hits[h] += 1
    print("     命中词: " + ", ".join("%s=%d" % kv for kv in hits.most_common()))
    print("     多词命中 %d 条 (%.1f%%)" % (multi, 100.0 * multi / len(recs)))

    venues = Counter(r.get("venue") for r in recs if r.get("venue"))
    print("     Top 期刊/会议:")
    for v, c in venues.most_common(8):
        print("       %4d  %s" % (c, v))

    no_abs = sum(1 for r in recs if not r.get("abstract"))
    no_doi = sum(1 for r in recs if not r.get("doi"))
    print("     缺摘要 %d (%.1f%%) / 缺DOI %d (%.1f%%)" % (
        no_abs, 100.0 * no_abs / len(recs), no_doi, 100.0 * no_doi / len(recs)))

    print("     抽样标题:")
    step = max(1, len(recs) // 10)
    for r in recs[::step][:10]:
        print("       [%s] %s" % (r.get("year"), (r.get("title") or "")[:90]))
    return len(recs)


def main():
    langs = sys.argv[1:] or ["en", "zh", "ar"]
    summary = {}
    for lang in langs:
        summary[lang] = report(lang)
    print("=" * 60)
    print("汇总: " + ", ".join("%s=%s" % (k, v if v is not None else "无")
                              for k, v in summary.items()))
    for lang, n in summary.items():
        if n is None:
            continue
        flag = "达标" if n >= 3000 else ("可做E0" if n >= 2000 else "不足")
        print("  %s: %d 条 -> %s (E0门槛2000/歧视性门槛3000)" % (lang, n, flag))


if __name__ == "__main__":
    main()
