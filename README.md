# tourism_and_world_model

文旅领域知识世界模型实验：中 / 英 / 阿三语文献，知识结构代谢 + 语言歧视性对比。

先实验，后写论文。不要求中阿双边。

## 文档

- [PLAN.md](PLAN.md) —— 执行方案与研究初稿（RQ、实验矩阵 E0–E3、验收门禁、常用命令）
- [任务清单.md](任务清单.md)

## 抓取

```bash
cd corpus
python fetch_tourism_ml.py --lang zh --year-from 2010 --year-to 2025 --per-year 800
python fetch_tourism_ml.py --lang ar --year-from 2010 --year-to 2025 --per-year 0
python fetch_tourism_ml.py --lang en --year-from 2010 --year-to 2025 --per-year 3000
```

- 试跑（人工抽检主题是否对）：`--lang zh --year-from 2024 --year-to 2024 --per-year 50`
- 断了续跑：加 `--resume`（按已写 id 去重）
- 输出：`corpus/data_v2/<lang>/works.jsonl`

依赖：`pip install requests`（后续实验另需 `pandas statsmodels`）
环境变量：`OPENALEX_API_KEY`（推荐；匿名走 mailto，容易被 429）

## 语料体检

```bash
cd corpus
python check_corpus.py en zh ar
```

远程：https://github.com/natebrashaf-rgb/tourism_and_world_model
