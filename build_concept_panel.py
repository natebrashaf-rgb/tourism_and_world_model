#!/usr/bin/env python3
"""构建概念面板 + 真值窗（E_2015 / E_2020）"""

import json
import os
import sys
from pathlib import Path
from collections import defaultdict, Counter
import pandas as pd
import numpy as np


def load_works(lang_dir):
    """加载单个语言目录的works.jsonl"""
    works = []
    file_path = lang_dir / "works.jsonl"
    if not file_path.exists():
        print(f"警告：{file_path} 不存在")
        return works
    
    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            try:
                work = json.loads(line.strip())
                works.append(work)
            except json.JSONDecodeError as e:
                print(f"警告：{file_path} 第{line_num}行JSON解析失败: {e}")
    return works


def extract_concepts(work):
    """从单个work中提取概念（keywords和topics）"""
    concepts = set()
    
    # 提取keywords
    if "keywords" in work and work["keywords"]:
        for kw in work["keywords"]:
            if "id" in kw:
                concepts.add(("keyword", kw["id"], kw.get("name", "")))
    
    # 提取topics（仅用于英文，中阿语料的topics是兜底垃圾）
    if work.get("language") == "en" and "topics" in work and work["topics"]:
        for topic in work["topics"]:
            if "id" in topic:
                concepts.add(("topic", topic["id"], topic.get("name", "")))
    
    return concepts


def build_concept_panel(data_dir, output_dir):
    """构建概念面板"""
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 加载三语数据
    all_works = []
    for lang in ["zh", "en", "ar"]:
        lang_dir = data_dir / lang
        works = load_works(lang_dir)
        print(f"加载 {lang}: {len(works)} 条记录")
        all_works.extend(works)
    
    if not all_works:
        print("错误：没有加载到任何数据")
        return None
    
    # 构建概念-年份频率矩阵
    # 格式：{concept_id: {year: count}}
    concept_year_freq = defaultdict(lambda: defaultdict(int))
    concept_info = {}  # {concept_id: (type, name)}
    year_totals = defaultdict(int)  # {year: total_works}
    
    for work in all_works:
        year = work.get("year")
        if not year:
            continue
        
        year_totals[year] += 1
        concepts = extract_concepts(work)
        
        for concept_type, concept_id, concept_name in concepts:
            concept_year_freq[concept_id][year] += 1
            if concept_id not in concept_info:
                concept_info[concept_id] = (concept_type, concept_name)
    
    # 转换为DataFrame
    years = sorted(year_totals.keys())
    concept_ids = sorted(concept_year_freq.keys())
    
    print(f"总年份范围: {min(years)}-{max(years)}")
    print(f"总概念数: {len(concept_ids)}")
    print(f"总工作数: {sum(year_totals.values())}")
    
    # 创建频率矩阵
    freq_matrix = np.zeros((len(concept_ids), len(years)))
    for i, concept_id in enumerate(concept_ids):
        for j, year in enumerate(years):
            freq_matrix[i, j] = concept_year_freq[concept_id].get(year, 0)
    
    # 归一化频率（每年内概念频率/该年总工作数）
    norm_matrix = np.zeros_like(freq_matrix)
    for j, year in enumerate(years):
        if year_totals[year] > 0:
            norm_matrix[:, j] = freq_matrix[:, j] / year_totals[year]
    
    # 创建DataFrame
    df_index = pd.DataFrame({
        "concept_id": concept_ids,
        "concept_type": [concept_info[cid][0] for cid in concept_ids],
        "concept_name": [concept_info[cid][1] for cid in concept_ids]
    })
    
    df_freq = pd.DataFrame(freq_matrix, columns=[f"freq_{y}" for y in years])
    df_norm = pd.DataFrame(norm_matrix, columns=[f"norm_{y}" for y in years])
    
    df = pd.concat([df_index, df_freq, df_norm], axis=1)
    
    # 保存为parquet
    parquet_path = output_dir / "panel.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"概念面板已保存到: {parquet_path}")
    
    return df, years, year_totals


def compute_emergence(df, years, T, window_size=5):
    """计算新兴概念（回溯式）
    
    只纳入 [T-4, T] 有非零历史频率的概念——
    零历史概念无法从时序预测，其 g_c 被 epsilon 放大至天文数字，
    会污染真值窗。"""
    # 窗口：T+1 到 T+window_size
    window_years = [y for y in years if T < y <= T + window_size]
    
    if len(window_years) < 3:
        print(f"警告：窗口 {T+1}-{T+window_size} 年份不足（只有{len(window_years)}年）")
        return None
    
    concept_ids = df["concept_id"].tolist()
    emergence_scores = []
    
    for idx, row in df.iterrows():
        concept_id = row["concept_id"]
        
        # 获取历史频率（T-4到T）
        hist_years = [y for y in years if T-4 <= y <= T]
        hist_freqs = []
        for y in hist_years:
            col = f"norm_{y}"
            if col in df.columns:
                hist_freqs.append(row[col])
        
        # 获取窗口频率
        window_freqs = []
        for y in window_years:
            col = f"norm_{y}"
            if col in df.columns:
                window_freqs.append(row[col])
        
        if not hist_freqs or not window_freqs:
            continue
        
        hist_mean = np.mean(hist_freqs)
        window_mean = np.mean(window_freqs)
        
        # 必须有非零历史——零历史概念无法从时序预测
        if hist_mean <= 0:
            continue
        
        # 存量 f_c(T)
        f_c_T = row.get(f"norm_{T}", 0)
        
        # 排除已饱和旧热点（f_c(T)过高者剔除）
        if f_c_T > 0.01:
            continue
        
        # 爆发度公式：g_c = (window_mean - hist_mean) / hist_mean
        g_c = (window_mean - hist_mean) / hist_mean
        
        emergence_scores.append({
            "concept_id": concept_id,
            "concept_type": row["concept_type"],
            "concept_name": row["concept_name"],
            "g_c": g_c,
            "f_c_T": f_c_T,
            "hist_mean": hist_mean,
            "window_mean": window_mean
        })
    
    if not emergence_scores:
        return None
    
    # 转换为DataFrame
    df_emergence = pd.DataFrame(emergence_scores)
    
    # 按爆发度排序，取前K%
    K = 20  # 取前20%
    df_emergence = df_emergence.sort_values("g_c", ascending=False)
    top_k = max(30, int(len(df_emergence) * K / 100))  # 至少30个
    
    df_top = df_emergence.head(top_k)
    
    return df_top


def main():
    # 设置路径
    base_dir = Path(__file__).parent
    data_dir = base_dir / "data" / "clean"
    output_dir = base_dir / "exp"
    
    # 构建概念面板
    print("构建概念面板...")
    result = build_concept_panel(data_dir, output_dir)
    
    if result is None:
        print("错误：构建概念面板失败")
        sys.exit(1)
    
    df, years, year_totals = result
    
    # 生成真值窗
    print("\n生成真值窗...")
    
    # E_2015: 截止2015，预测2016-2020
    print("计算 E_2015 (截止2015，预测2016-2020)...")
    E_2015 = compute_emergence(df, years, T=2015, window_size=5)
    if E_2015 is not None:
        print(f"E_2015: {len(E_2015)} 个新兴概念")
        # 保存
        E_2015_path = output_dir / "windows" / "E_2015.json"
        E_2015_path.parent.mkdir(parents=True, exist_ok=True)
        E_2015.to_json(E_2015_path, orient="records", indent=2)
        print(f"E_2015 已保存到: {E_2015_path}")
    else:
        print("警告：E_2015 计算失败")
    
    # E_2020: 截止2020，预测2021-2025
    print("计算 E_2020 (截止2020，预测2021-2025)...")
    E_2020 = compute_emergence(df, years, T=2020, window_size=5)
    if E_2020 is not None:
        print(f"E_2020: {len(E_2020)} 个新兴概念")
        # 保存
        E_2020_path = output_dir / "windows" / "E_2020.json"
        E_2020_path.parent.mkdir(parents=True, exist_ok=True)
        E_2020.to_json(E_2020_path, orient="records", indent=2)
        print(f"E_2020 已保存到: {E_2020_path}")
    else:
        print("警告：E_2020 计算失败")
    
    # 输出统计信息
    print("\n=== 概念面板统计 ===")
    print(f"总概念数: {len(df)}")
    print(f"年份范围: {min(years)}-{max(years)}")
    print(f"每年工作数:")
    for year in sorted(year_totals.keys()):
        print(f"  {year}: {year_totals[year]}")
    
    # 检查门禁：每窗|E|≥30
    print("\n=== 门禁检查 ===")
    if E_2015 is not None:
        print(f"E_2015: {len(E_2015)} ≥ 30? {'✅' if len(E_2015) >= 30 else '❌'}")
    if E_2020 is not None:
        print(f"E_2020: {len(E_2020)} ≥ 30? {'✅' if len(E_2020) >= 30 else '❌'}")
    
    print("\n概念面板构建完成！")


if __name__ == "__main__":
    main()