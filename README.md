# tourism_and_world_model

文旅领域知识世界模型实验：中 / 英 / 阿三语文献，知识结构代谢 + 语言歧视性对比。

先实验，后写论文。不要求中阿双边。

## 文档

- [实验设计.md](实验设计.md)
- [语料计划.md](语料计划.md)
- [任务清单.md](任务清单.md)

## 抓取

```bash
cd corpus
python fetch_tourism_trilingual.py --lang en --out data_en --max 4000
python fetch_tourism_trilingual.py --lang zh --out data_zh --max 4000
python fetch_tourism_trilingual.py --lang ar --out data_ar --max 4000
```

依赖：`pip install requests`  
环境变量：`OPENALEX_API_KEY`（推荐）

远程：https://github.com/natebrashaf-rgb/tourism_and_world_model
