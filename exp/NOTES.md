# 实验笔记

> 本文件在 2026-09-26 被整体订正。此前版本把 429 的成因判断错了（写成"带 search= 触发限流"，
> 并建议"转 Crossref""等一天"），实际是本机 IP 的整个 OpenAlex 匿名池被封，与 search 无关。

## 一、抓取通路（关键坑）

### 现象
OpenAlex 从本机 IP 发起的一切请求都返回 429：`/works`、`/topics`、`/authors`、`/sources`、
`/institutions` 全部一样，连不带 `search=` 的普通 filter 也不例外。
响应头 `Retry-After` 是**假值**（观测到 55193 → 52200 → 52055，滑动不归零），所以"等额度恢复"
永远等不到。实测：连续 12 次普通 filter 请求（间隔 2s）12 次全 429。

### 解法
经 `r.jina.ai` 中转，OpenAlex 看到的是它的出口 IP，请求全部 200。
脚本里加了 `--transport direct|jina` 开关（默认 direct，不影响原行为）。

**两个必须记住的坑**（都踩过，都表现为"静默返回 0 条"，不报错）：

1. **Accept 头**：会话默认 `Accept: application/json` 会让 r.jina.ai 包一层
   `{"code":200,"data":{"content":"..."}}` 信封，直接 `r.json()` 拿到的是信封、
   取不到 `results` → 写出 0 条。必须显式覆盖为 `Accept: text/plain`
   + `x-return-format: text`。
2. **jina 自己的限流**：偶尔返回 429，但它的 `Retry-After` 是**真实值**（如 1 秒），
   与 OpenAlex 的假值不同，正常退避即可。

- 速度：约 3–4 秒 / 200 条。
- 长期方案：申请 OpenAlex 免费 API Key（10 万次/天），可直接绕过 IP 封禁。

## 二、词表与主题精度（本项目最大的方法论发现）

### 发现 1：全量词表把大量非文旅文献带进来

`validate_corpus.py` 新增"严格文旅词命中率"报告项（非门禁），衡量标题/摘要是否至少
含一个"一眼是文旅"的词：

| 语种 | 全量词表命中率 | 典型误召回 |
|---|---|---|
| en | 62.2% | *Future decision-making without episodic **mental time travel*** |
| zh | 41.3% | 「赣南和赣北-皖南**钨成矿带**含钨花岗岩…」「**高等数学**教学方法的探讨」 |
| ar | 22.8% | 伊斯兰圣训研究、学校管理变革、恐慌症干预、科威特室内设计 |

根因是词表里的**单独成词的宽泛词**：中文的「文化」、阿语的 `ثقاف / التراث`、
英文的 `culture / travel / leisure`。在学术写作里这些词遍地都是，
等于用"文化"当检索词去查文献。

### 发现 2：OpenAlex 的 search **不做短语匹配**

`title_and_abstract.search:` 会把多词短语和带连字符的词**拆成 token** 做 OR：

- `"tourist attraction"` → `tourist` **或** `attraction`
  → 召回 *Level attraction in circuit electromechanics*、*Attraction of pest thrips*，
  甚至 *Gametophytic Pollen Tube Guidance: **Attractant** Peptides*
- `"eco-tourism"` → `eco` 或 `tourism`
  → 召回 *Building an **Eco**-Innovation Cluster*

实测：短语版英文语料 47,921 条里，**45%（21,550 条）不含任何核心旅游词**。
去掉短语/连字符词后重抓，命中率从 56.2% 升到 **97.6%**。

**结论：词表里只能放单 token 的词，短语一律不可靠。**

### 收窄词表（`--wordlist strict`）
去掉过宽单字词，只保留真·文旅词；英文只留单 token。
运行：`fetch_tourism_ml.py --wordlist strict --out-dir data_v2_strict`

## 三、抓取结果（2026-09-26）

命令：`--year-from 2010 --year-to 2025 --transport jina`，年份上限 ar=2000 / zh=800 / en=3000。

| 语种 | 全量词表（data_v2/） | 收窄词表（data_v2_strict/） | 收窄后严格词命中 |
|---|---|---|---|
| en | 6,000（**未跑完**，只到 2011） | **47,882** | **97.6%** |
| zh | 12,799 | **8,018** | 88.4% |
| ar | 27,199 | **2,744** | **100.0%** |

## 四、门禁结果（`validate_corpus.py --data-dir data_v2_strict`）

| 门禁 | en | zh | ar |
|---|---|---|---|
| 总量 | ✅ 47,882 ≥ 40,000 | ✅ 8,018 ≥ 8,000 | ❌ 2,744 < 8,000 |
| 每语每年 ≥ 300 | ✅ | ❌ 6 个年份不足 | ❌ 14 个年份不足 |
| language 一致 ≥ 99% | ✅ 100% | ✅ 100% | ✅ 100% |
| 题名非空 100% | ✅ | ✅ | ✅ |
| keywords∪topics ≥ 80% | ✅ 100% | ✅ 99.9% | ✅ 100% |
| id 重复 0 | ✅ | ✅ | ✅ |

### 两处不达标的原因

**ar 只有 2,744 条**：这是 OpenAlex 里阿语文旅文献的**真实总量**，不是抓取失败。
收窄后严格词命中 100%，即这批数据很干净，但规模就是这么大。
PLAN.md 的 8,000 门禁对阿语不可达。
参考 PLAN 自己的规则（< 1,000 条才放弃 E2/E3）：2,744 > 1,000，E0 成立，
E2/E3 歧视性实验处于 3,000 门槛之下、勉强可用。

**zh 2017 年后逐年不足**：2010–2016 每年都顶到 800 上限（说明池子更大），
2017 年起骤降（2017:318、2018:199、2023:82）。这不是词表问题，而是
OpenAlex 对**近年中文文献的 `language:zh` 标注覆盖在下降**（或收录变少）。

### 附带发现：中/阿语文献的 topic 是兜底垃圾
`Military Technology and Strategies` / `Legal and Regulatory Analysis` /
`Linguistic, Cultural, and Literary Studies` 三个 topic 在 zh、ar 语料里计数几乎相同
（ar: 2072/2073/2091，zh: 6804/6805/6806），是 OpenAlex 分类不了时的兜底填充。
**PLAN 的"概念轴 = keywords 主 + topics 辅"对中阿两语是瘸的，topics 那一半不可用**，
Day2 建概念面板只能靠 keywords（英文 topics 正常，可用）。

## 五、待决（需研究口径决策，不是技术问题）

1. **ar 用 2,744 条干净数据，还是回头用 27,199 条里 77% 噪声的？**
   前者干净但远低于门禁；后者过门禁但基本不能用来谈"阿语知识代谢"。
2. **zh 2017 年后年份不足 300 怎么处理？** 放宽该门禁、缩窗口，还是补中文源（知网）？
3. **是否申请 OpenAlex API Key**：申请后可直接直连，不再依赖 r.jina.ai 中转。

## 六、目录现状

```
data_v2/{ar,zh,en}/works.jsonl          全量词表结果（EN 未跑完，可 --resume 续跑）
data_v2_strict/{ar,zh,en}/works.jsonl   收窄词表结果（推荐使用）
data_v2_strict/en/works_短语版词表.bak.jsonl   短语版英文语料，留作精度对照证据
exp/fetch_all.log / fetch_strict.log / fetch_strict_en2.log   抓取日志
exp/validate_corpus_strict.txt          门禁验收输出
```

`data_v2*` 全部在 `.gitignore` 内，不入库。
