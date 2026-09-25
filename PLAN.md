# 文旅概念时序世界模型 — 执行方案与研究初稿

> 模式：主题/概念时序模型（DTM/关键词频时序 + ARIMA/回归），回溯式 5 年窗预测。  
> 节奏：Day1 抓取+验证+清晰；Day2 实验。先实验，后写论文。

---

## 一、研究初稿方案

### 1. 题目候选

1. 多语言文旅知识结构代谢：基于概念时序的世界模型回测研究  
2. Cross-lingual Knowledge Metabolism in Culture-Tourism Research  
3. 语言权重对新兴概念预测的影响：中·英·阿文旅文献对比实验  

### 2. 贡献一句话

在文旅领域用概念时序世界模型做 5 年周期回溯预测，对比中·英·阿知识代谢与可预测性，并验证提升阿拉伯语权重是否改善阿语新兴概念命中率。

### 3. 研究问题

| # | 问题 | 实验 |
|---|---|---|
| RQ1 | 单语文旅概念结构对「未来 5 年升温概念」是否可预测？ | E0（单语成立即可成文） |
| RQ2 | 三语预测趋近真实程度是否有系统差异？ | E0 横比 + E1 |
| RQ3 | 调整语言权重能否定向提升该语言命中率？ | E2/E3 |

### 4. 操作化定义

**新兴概念**（回溯式，截止年 T，窗 W=[T+1,T+5]）：

- 存量 \(f_c(T)\)：截止 T 的归一化频率  
- 爆发度 \(g_c = (\bar f_c(W) - \bar f_c(T-4,T)) / (\bar f_c(T-4,T)+\epsilon)\)  
- \(E_T^{(K)}\)：爆发度前 K%，且排除已饱和旧热点（\(f_c(T)\) 过高者剔除）

**世界模型**：\(\{f_c(t)\}_{t\le T} \to\) 未来爆发排序。模型族 = 频率时序外推。

**知识结构代谢**：概念半衰期、年度新进入 Top 比例、新兴命中率。

### 5. 方法摘要

- 数据：OpenAlex，zh/en/ar，2010–2025，题摘文旅词过滤；概念轴 = keywords（跨语言同 ID）主 + topics 辅  
- 规模验收：ar≥8k、zh≥8k、en≥40k、每年≥300、概念字段覆盖≥80%  
- 预测器：M1 对数线性趋势、M2 ARIMA(1,1,0)/ETS、M3 增速惯性、M4 共现加权（可选）  
- 回测窗：≤2015→2016–2020；≤2020→2021–2025（可选更早窗）  
- 指标：P@10、P@20、R@20、预测 Top20 vs 真实 Top20 余弦/JS  
- 权重：\(S_c(\alpha)=\sum_\ell \alpha_\ell \tilde g_{\ell,c}\)（语种内 z-score）

| 实验 | 设置 | 假设 |
|---|---|---|
| E0 | 三语各自单语 | H1：P@10 > 随机 |
| E1 | α=(1,1,1) | 多语基线 |
| E2 | α_ar ∈ {0.2,0.5,1,2} | H2：α_ar↑ → 阿语 P@K↑ |
| E3 | 对称升 zh/en | 权重效应对照 |

### 6. 风险预案

| 风险 | 预案 |
|---|---|
| 阿语 keyword 覆盖低 | topics.id + 题名词双轨 |
| 中文量少 | 中文词表；调 K%/窗口 |
| ARIMA 不稳 | 回退 M1/M3 |
| 429 | 分年、delay、mailto、en 抽样 |
| 仅 2 个 5 年窗 | 加历史窗；bootstrap CI |

---

## 二、详细执行方案

### 仓库结构（目标）

```
fetch_openalex_ar_culture_tourism.py   # 旧中阿脚本，不动
data_test/                             # 旧结果，不动
PLAN.md                                # 本文档
fetch_tourism_ml.py                    # 三语爬虫
validate_corpus.py                     # 验收统计
build_concept_panel.py                 # 概念面板 + 真值窗
run_forecast.py                        # E0–E3 回测
exp/                                   # 结果与笔记
data_v2/{zh,en,ar}/works.jsonl
```

### Day1

1. `fetch_tourism_ml.py --lang zh|en|ar --year-from 2010 --year-to 2025 --per-year N`
   - 中文词表新增；去中阿约束；分年抓取；OpenAlex id 去重
   - 先试跑：`zh 2024, per-year 50` 人工抽检 → 再全量（ar→zh→en）
2. `validate_corpus.py` 全部门禁通过  
3. 清数据、删 `__pycache__`、`exp/NOTES.md` 记参数  

### Day2

1. `build_concept_panel.py` → `exp/panel.parquet` + `E_2015`/`E_2020`（|E|≥30）  
2. `run_forecast.py` E0→E1→E2→E3 → `exp/results.csv`、`results_alpha.csv`  
3. 主表回填本文件「预期结果」  

### 验收门禁

| 项 | 线 |
|---|---|
| ar / zh | ≥ 8000 |
| en | ≥ 40000 |
| 每语每年 | ≥ 300 |
| language 一致 | ≥ 99% |
| 题名非空 | 100% |
| keywords∪topics 覆盖 | ≥ 80% |
| id 重复 | 0 |
| 每窗 \|E\| | ≥ 30 |

### 常用命令

```bat
pip install requests pandas statsmodels

python fetch_tourism_ml.py --lang zh --year-from 2024 --year-to 2024 --per-year 50
python fetch_tourism_ml.py --lang ar --year-from 2010 --year-to 2025 --per-year 0
python fetch_tourism_ml.py --lang zh --year-from 2010 --year-to 2025 --per-year 800
python fetch_tourism_ml.py --lang en --year-from 2010 --year-to 2025 --per-year 3000

python validate_corpus.py
python build_concept_panel.py
python run_forecast.py --stage all
```

### 交付物

- [ ] `data_v2/*/works.jsonl` + `validate_corpus.txt`  
- [ ] `exp/panel.parquet`、`exp/windows/*.json`  
- [ ] `exp/results.csv`、`exp/results_alpha.csv`  
- [ ] `exp/NOTES.md` 数字结论  
- [ ] 主表三张（E0 / α 扫描 / 代谢描述）  
