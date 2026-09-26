# tourism_and_world_model

文旅领域知识世界模型实验：中 / 英 / 阿三语文献，知识结构代谢 + 语言歧视性对比。

先实验，后写论文。不要求中阿双边。

## 文档

- [PLAN.md](PLAN.md) —— 执行方案与研究初稿（RQ、实验矩阵 E0–E3、操作化定义、验收门禁、Day1/Day2）
- [任务清单.md](任务清单.md) —— 进度勾选
- [data/README.md](data/README.md) —— 两套语料库（raw / clean）的对照与取舍
- [exp/NOTES.md](exp/NOTES.md) —— 实验笔记（通路坑、词表精度实测、门禁结果）

## 目录

```
PLAN.md                执行方案与研究初稿
fetch_tourism_ml.py    三语爬虫（OpenAlex）
validate_corpus.py     语料验收（PLAN.md 门禁 + 主题精度报告项）
build_concept_panel.py 概念面板 + 真值窗   ← 待建
run_forecast.py        E0–E3 回测          ← 待建
data/
  README.md            两库说明
  raw/{en,zh,ar}/works.jsonl     全量词表结果（召回宽、噪声大）
  clean/{en,zh,ar}/works.jsonl   收窄词表结果（召回窄、精度高）← 默认用这个
  _archive/            对照留档
exp/                   结果与笔记
```

## 抓取

```bash
# 推荐：收窄词表 → 自动写入 data/clean/<lang>/works.jsonl
python fetch_tourism_ml.py --lang ar --year-from 2010 --year-to 2025 --per-year 2000 \
    --wordlist strict --transport jina
python fetch_tourism_ml.py --lang zh --year-from 2010 --year-to 2025 --per-year 800 \
    --wordlist strict --transport jina
python fetch_tourism_ml.py --lang en --year-from 2010 --year-to 2025 --per-year 3000 \
    --wordlist strict --transport jina
```

参数说明：

| 参数 | 用途 |
|---|---|
| `--wordlist full\|strict` | `full` = PLAN.md 原词表（→ `data/raw`）；`strict` = 收窄词表（→ `data/clean`）。**推荐 strict**，全量词表实测 22–62% 是噪声 |
| `--transport direct\|jina` | `direct` 直连；`jina` 经 `r.jina.ai` 中转换出口 IP。**本机 IP 已被 OpenAlex 整个匿名池 429，必须用 jina** |
| `--resume` | 按已写 id 去重续跑 |
| `--out-dir` | 覆盖输出根目录；不填则按词表自动选 `data/raw` 或 `data/clean` |

**词表里只能放单 token 的词**：OpenAlex 的 `title_and_abstract.search` 不做短语匹配，
`"tourist attraction"` 会被拆成 `tourist` 或 `attraction`，把物理、植物学的论文也召回。
详见 `exp/NOTES.md`。

## 验收

```bash
python validate_corpus.py                              # 默认验 data/clean
python validate_corpus.py --data-dir data/raw --out exp/validate_corpus_raw.txt
```

门禁：ar / zh ≥ 8,000；en ≥ 40,000；每语每年 ≥ 300；language 一致 ≥ 99%；
题名非空 100%；keywords∪topics 覆盖 ≥ 80%；id 重复 0。

另报一项**主题精度**（严格文旅词命中率，非门禁），用于判断语料能不能用来谈"知识代谢"。

依赖：`pip install requests`（后续实验另需 `pandas statsmodels`）
环境变量：`OPENALEX_API_KEY`（有 key 可直接直连，不必走 jina）

远程：https://github.com/natebrashaf-rgb/tourism_and_world_model
