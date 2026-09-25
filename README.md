# tourism_and_world_model

文旅领域知识世界模型实验：中 / 英 / 阿三语文献，知识结构代谢 + 语言歧视性对比。

先实验，后写论文。不要求中阿双边。

## 文档

- [PLAN.md](PLAN.md) —— 执行方案与研究初稿（RQ、实验矩阵 E0–E3、操作化定义、验收门禁、Day1/Day2）
- [任务清单.md](任务清单.md) —— 进度勾选

## 目录

```
PLAN.md                执行方案与研究初稿
fetch_tourism_ml.py    三语爬虫（OpenAlex）
validate_corpus.py     语料验收（PLAN.md 门禁）
build_concept_panel.py 概念面板 + 真值窗   ← 待建
run_forecast.py        E0–E3 回测          ← 待建
exp/                   结果与笔记
data_v2/{zh,en,ar}/works.jsonl   抓取产物（不入库）
```

## 抓取

```bash
# 试跑，人工抽检主题是否真是文旅
python fetch_tourism_ml.py --lang zh --year-from 2024 --year-to 2024 --per-year 50

# 全量，顺序 ar → zh → en
python fetch_tourism_ml.py --lang ar --year-from 2010 --year-to 2025 --per-year 0
python fetch_tourism_ml.py --lang zh --year-from 2010 --year-to 2025 --per-year 800
python fetch_tourism_ml.py --lang en --year-from 2010 --year-to 2025 --per-year 3000
```

- 断了续跑：加 `--resume`（按已写 id 去重）
- 输出：`data_v2/<lang>/works.jsonl`

## 验收

```bash
python validate_corpus.py          # 三语全验，结果写入 validate_corpus.txt
```

门禁：ar / zh ≥ 8,000；en ≥ 40,000；每语每年 ≥ 300；language 一致 ≥ 99%；
题名非空 100%；keywords∪topics 覆盖 ≥ 80%；id 重复 0。

依赖：`pip install requests`（后续实验另需 `pandas statsmodels`）
环境变量：`OPENALEX_API_KEY`（推荐；匿名走 mailto，容易被 429）

远程：https://github.com/natebrashaf-rgb/tourism_and_world_model
