# -*- coding: utf-8 -*-
"""
语料验收（PLAN.md「验收门禁」）

读 data_v2/<lang>/works.jsonl，逐条门禁判定，结果打印并写入 validate_corpus.txt。

用法:
    python validate_corpus.py                 # 三语全验
    python validate_corpus.py zh ar           # 指定语种
    python validate_corpus.py --data-dir data_v2 --out validate_corpus.txt
"""

import argparse
import json
import os
import sys
from collections import Counter

# PLAN.md「验收门禁」
GATE_TOTAL = {"ar": 8000, "zh": 8000, "en": 40000}
GATE_PER_YEAR = 300          # 每语每年
GATE_LANG_CONSISTENCY = 0.99  # language 一致
GATE_TITLE_NONEMPTY = 1.00    # 题名非空
GATE_CONCEPT_COVERAGE = 0.80  # keywords ∪ topics 覆盖
GATE_ID_DUP = 0               # id 重复

# 严格文旅词（只保留"一眼是文旅"的核心词）。用于估算主题精度：
# 词表里的宽泛词（文化 / ثقاف / culture / travel）会把非文旅文献带进来，
# 命中宽泛词的记录未必真是文旅，命中严格词的则基本可信。
# 这是"报告项"，不是 PLAN 的门禁项。
STRICT_TERMS = {
    "en": ["tourism", "tourist", "hospitality", "cultural heritage",
           "cultural tourism", "destination", "pilgrimage", "eco-tourism",
           "intangible heritage", "museum"],
    "zh": ["旅游", "文旅", "旅游业", "文化旅游", "遗产旅游", "生态旅游",
           "乡村旅游", "博物馆", "非物质文化遗产"],
    "ar": ["السياحة", "سياحة", "سياحي", "سياحية", "السياحي", "سياح",
           "الضيافة", "ضيافة", "المتاحف", "متحف"],
}


def load_jsonl(path):
    """返回 (记录列表, 重复 id 次数)。坏行跳过并计数。"""
    recs, ids, bad = [], [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                bad += 1
                continue
            recs.append(r)
            rid = (r.get("id") or "").strip()
            if rid:
                ids.append(rid)
    dup = sum(c - 1 for c in Counter(ids).values() if c > 1)
    return recs, dup, bad


def has_concept(r):
    return bool(r.get("keywords")) or bool(r.get("topics"))


def check_lang(lang, data_dir):
    path = os.path.join(data_dir, lang, "works.jsonl")
    lines = []
    if not os.path.exists(path):
        return ["[%s] 未抓取：%s 不存在" % (lang, path)], False, 0

    recs, dup, bad = load_jsonl(path)
    n = len(recs)
    lines.append("[%s] 文件 %s" % (lang, path))
    lines.append("[%s] 记录 %d 条（坏行 %d）" % (lang, n, bad))
    if n == 0:
        lines.append("[%s] 空文件" % lang)
        return lines, False, 0

    years = Counter(r.get("year") for r in recs)
    span = sorted(y for y in years if isinstance(y, int))
    if span:
        lines.append("[%s] 年份 %d-%d" % (lang, span[0], span[-1]))
        lines.append("[%s] 年份分布 %s" % (
            lang, " ".join("%d:%d" % (y, years[y]) for y in span)))
        thin = [(y, years[y]) for y in range(span[0], span[-1] + 1)
                if years.get(y, 0) < GATE_PER_YEAR]
    else:
        span, thin = [], []
        lines.append("[%s] 年份字段全空" % lang)

    types = Counter(r.get("type") for r in recs)
    lines.append("[%s] 类型 %s" % (
        lang, ", ".join("%s=%d" % kv for kv in types.most_common(6))))

    lang_ok = sum(1 for r in recs if r.get("language") == lang)
    title_ok = sum(1 for r in recs if (r.get("title") or "").strip())
    concept_ok = sum(1 for r in recs if has_concept(r))
    lang_ratio = lang_ok / float(n)
    title_ratio = title_ok / float(n)
    concept_ratio = concept_ok / float(n)

    top_topics = Counter()
    top_kws = Counter()
    for r in recs:
        for t in r.get("topics") or []:
            top_topics[(t.get("id"), t.get("name"))] += 1
        for k in r.get("keywords") or []:
            top_kws[(k.get("id"), k.get("name"))] += 1
    if top_topics:
        lines.append("[%s] Top topics %s" % (lang, ", ".join(
            "%s(%d)" % (nm or tid, c) for (tid, nm), c in top_topics.most_common(6))))
    if top_kws:
        lines.append("[%s] Top keywords %s" % (lang, ", ".join(
            "%s(%d)" % (nm or kid, c) for (kid, nm), c in top_kws.most_common(6))))

    gate_total = GATE_TOTAL.get(lang, 0)
    checks = [
        ("总量 ≥ %d" % gate_total, "%d" % n, n >= gate_total),
        ("每语每年 ≥ %d" % GATE_PER_YEAR,
         "不达标年份 %d 个%s" % (len(thin), ("（%s）" % thin[:6] if thin else "")),
         not thin),
        ("language 一致 ≥ %.0f%%" % (GATE_LANG_CONSISTENCY * 100),
         "%.1f%%" % (lang_ratio * 100), lang_ratio >= GATE_LANG_CONSISTENCY),
        ("题名非空 = %.0f%%" % (GATE_TITLE_NONEMPTY * 100),
         "%.1f%%" % (title_ratio * 100), title_ratio >= GATE_TITLE_NONEMPTY),
        ("keywords∪topics 覆盖 ≥ %.0f%%" % (GATE_CONCEPT_COVERAGE * 100),
         "%.1f%%" % (concept_ratio * 100), concept_ratio >= GATE_CONCEPT_COVERAGE),
        ("id 重复 = %d" % GATE_ID_DUP, "%d" % dup, dup <= GATE_ID_DUP),
    ]

    lines.append("[%s] —— 门禁 ——" % lang)
    allpass = True
    for name, got, ok in checks:
        lines.append("[%s]   %s %s   实际 %s" % (
            lang, "[通过]" if ok else "[未过]", name, got))
        allpass = allpass and ok
    lines.append("[%s] 结论：%s" % (lang, "全部门禁通过" if allpass else "有门禁未过"))

    # 报告项（非门禁）：严格文旅词命中率 + 抽样标题，供人工抽检
    strict = STRICT_TERMS.get(lang, [])
    s_hit = sum(1 for r in recs
                if any(t.lower() in ((r.get("title") or "") + " " + (r.get("abstract") or "")).lower()
                       for t in strict))
    lines.append("[%s] 报告项：严格文旅词命中 %.1f%%（%d/%d）——非门禁，用于估主题精度"
                 % (lang, 100.0 * s_hit / float(n), s_hit, n))
    lines.append("[%s] 抽样标题（每 %d 条取 1 条，共 12 条，供人工抽检）："
                 % (lang, max(1, n // 12)))
    step = max(1, n // 12)
    for r in recs[::step][:12]:
        lines.append("[%s]   %s | %s" % (lang, r.get("year"),
                                         (r.get("title") or "")[:78]))
    return lines, allpass, n


def main():
    ap = argparse.ArgumentParser(description="语料验收（PLAN.md 门禁）")
    ap.add_argument("langs", nargs="*", default=None,
                    help="语种，默认 en zh ar")
    ap.add_argument("--data-dir", default="data_v2")
    ap.add_argument("--out", default="validate_corpus.txt")
    args = ap.parse_args()

    langs = args.langs or ["en", "zh", "ar"]
    out_lines = []
    summary = {}
    for lang in langs:
        lines, ok, n = check_lang(lang, args.data_dir)
        out_lines.extend(lines)
        out_lines.append("")
        summary[lang] = (ok, n)

    out_lines.append("汇总：" + "  ".join(
        "%s=%s(%d 条)" % (l, "过" if ok else "未过", n) for l, (ok, n) in summary.items()))
    text = "\n".join(out_lines)
    print(text, flush=True)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("\n已写入 %s" % args.out, flush=True)

    sys.exit(0 if all(ok for ok, _ in summary.values()) else 1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
