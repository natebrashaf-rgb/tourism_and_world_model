# data/ —— 两套语料库

同一批抓取脚本、同一时间窗（2010–2025）、同一数据源（OpenAlex），
**唯一的区别是检索词表**。两库并存，供对照取用。

```
data/
  raw/{en,zh,ar}/works.jsonl      全量词表（PLAN.md 原词表）—— 召回宽、噪声大
  clean/{en,zh,ar}/works.jsonl    收窄词表（--wordlist strict）—— 召回窄、精度高
  _archive/en_短语版词表.bak.jsonl  clean 的中间版本，仅作精度对照证据
```

## 两库对照（2026-09-26）

| 语种 | raw 条数 | raw 主题精度 | clean 条数 | clean 主题精度 |
|---|---|---|---|---|
| en | 6,000 ⚠️ **未跑完** | 62.2% | 47,882 | **97.6%** |
| zh | 12,799 | 41.3% | 8,018 | 88.4% |
| ar | 27,199 | 22.8% | 2,744 | **100.0%** |

> **主题精度** = 标题或摘要里至少含一个"一眼是文旅"的严格词的记录占比。
> 由 `validate_corpus.py` 作为**报告项**输出（不是门禁）。

⚠️ `raw/en` 只抓到 2010–2011 两年就被中断（目标 40,000）。
它与另外两语的 raw 不可比，**别拿它做跨语种对比**。
需要补全就重跑（`--resume` 可续）：

```bash
python fetch_tourism_ml.py --lang en --year-from 2010 --year-to 2025 \
    --per-year 3000 --wordlist full --transport jina --resume
```

## 该用哪个

**默认用 `clean`。** raw 库的噪声不是"差一点"——阿语 77% 的标题跟文旅无关
（圣训研究、学校管理、恐慌症干预），拿它谈"阿语知识代谢"结论不成立。

raw 库留着有两个用处：一是可复现"换词表 → 精度变化"的对照，
二是 clean 词表若在某些主题上有系统性漏检，可以从 raw 里补捞。

## raw 为什么脏

词表里的**单独成词的宽泛词**：中文「文化」、阿语 `ثقاف / التراث`、
英文 `culture / travel / leisure`。这些词在学术写作里遍地都是，
等于用「文化」当检索词。clean 词表把它们去掉，只留真·文旅词。

另外两个抓取层面的坑（详见 `../exp/NOTES.md`）：

1. **OpenAlex 的 `title_and_abstract.search` 不做短语匹配。**
   `"tourist attraction"` 会被拆成 `tourist` 或 `attraction`，
   于是把 *Level attraction in circuit electromechanics*、*Attraction of pest thrips*
   也召回了——短语版英文语料 47,921 条里 45% 不含任何核心旅游词。
   **词表里只能放单 token 的词。**
2. **本机 IP 被 OpenAlex 整个匿名池 429**，必须 `--transport jina` 才能抓。

## 重建

```bash
# raw
python fetch_tourism_ml.py --lang <L> --year-from 2010 --year-to 2025 \
    --per-year <N> --wordlist full  --transport jina --out-dir data/raw   --resume
# clean
python fetch_tourism_ml.py --lang <L> --year-from 2010 --year-to 2025 \
    --per-year <N> --wordlist strict --transport jina --out-dir data/clean --resume

# 验收（默认就查 data/clean）
python validate_corpus.py --data-dir data/clean --out exp/validate_corpus_clean.txt
python validate_corpus.py --data-dir data/raw   --out exp/validate_corpus_raw.txt
```

年份上限本次用的是 ar=2000（raw 用 0 不截断）/ zh=800 / en=3000。
