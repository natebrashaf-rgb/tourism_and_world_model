#!/usr/bin/env python3
"""运行回测实验（E0→E1→E2→E3）

按 PLAN.md 定义：
- 概念 c 在截止年 T 的爆发度 g_c = (mean_f(W) - mean_f(T-4..T)) / (mean_f(T-4..T) + eps)
- 预测器基于 [T-4, T] 的时序外推未来频率，再算预测 g_c
- 按预测 g_c 排序，与真实 g_c 排序对比
"""

import json
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from scipy.spatial.distance import cosine, jensenshannon

import warnings
warnings.filterwarnings('ignore')


def extract_years(df):
    norm_cols = sorted([c for c in df.columns if c.startswith('norm_')],
                       key=lambda c: int(c.split('_')[1]))
    years = [int(c.split('_')[1]) for c in norm_cols]
    return norm_cols, years


def get_freq(row, year):
    col = f'norm_{year}'
    return row.get(col, 0.0) if col in row.index else 0.0


def predict_trend(row, years, T):
    """趋势预测：对 [T-4..T] 有非零数据的概念做 log-linear 外推；无历史则返回 0"""
    vals = []
    for y in years:
        if T - 4 <= y <= T:
            v = get_freq(row, y)
            if v > 0:
                vals.append((y, np.log(v)))
    if len(vals) < 2:
        return 0.0
    x = np.array([v[0] for v in vals])
    y_arr = np.array([v[1] for v in vals])
    slope = np.polyfit(x, y_arr, 1)[0]
    future_years = np.arange(T + 1, T + 6)
    pred = np.exp(y_arr[-1] + slope * (future_years - x[-1]))
    return float(np.clip(np.mean(pred), 0, 1))


def predict_momentum(row, years, T):
    """M3: 增速惯性——用 [T-2..T] 的增长率外推"""
    recent = [get_freq(row, y) for y in years if T - 2 <= y <= T]
    if len(recent) < 2 or recent[0] <= 0:
        return 0.0
    growth = (recent[-1] - recent[0]) / recent[0]
    return growth


def predict_log_slope(row, years, T):
    """M1: 对 [T-4..T] 做 log-linear 回归，返回斜率（增长率代理）"""
    vals = []
    for y in years:
        if T - 4 <= y <= T:
            v = get_freq(row, y)
            if v > 0:
                vals.append((y, np.log(v)))
    if len(vals) < 2:
        return 0.0
    x = np.array([v[0] for v in vals])
    y_arr = np.array([v[1] for v in vals])
    slope = np.polyfit(x, y_arr, 1)[0]
    return float(slope)


def predict_g_c(row, years, T, method='momentum'):
    """用趋势预测值计算预测爆发度 g_c"""
    hist_vals = [get_freq(row, y) for y in years if T - 4 <= y <= T]
    hist_mean = np.mean(hist_vals) if hist_vals else 0.0
    if hist_mean <= 0:
        return 0.0

    if method == 'momentum':
        # M3: 增速惯性
        return predict_momentum(row, years, T)
    elif method == 'log_slope':
        # M1: log-linear 斜率
        return predict_log_slope(row, years, T)
    else:
        # 原始方法：预测均值 vs 历史均值
        pred_future = predict_trend(row, years, T)
        g_c = (pred_future - hist_mean) / hist_mean
        return float(g_c)


def compute_metrics(ranked_pred, ranked_truth, k=20):
    """P@k 和 R@k"""
    pred_set = set(ranked_pred[:k])
    truth_set = set(ranked_truth[:k])
    hits = len(pred_set & truth_set)
    return hits / k, hits / len(truth_set) if truth_set else 0.0


def compute_score_similarity(pred_scores, truth_scores, method='cosine'):
    """对两个排序向量计算相似度"""
    n = min(len(pred_scores), len(truth_scores))
    p, t = pred_scores[:n], truth_scores[:n]
    if method == 'cosine':
        if np.linalg.norm(p) > 0 and np.linalg.norm(t) > 0:
            return 1 - cosine(p, t)
        return 0.0
    elif method == 'js':
        p_norm = p / (np.sum(p) + 1e-10)
        t_norm = t / (np.sum(t) + 1e-10)
        return 1 - jensenshannon(p_norm, t_norm)
    return 0.0


def filter_old_hot(df, T, percentile=80):
    """排除已饱和旧热点：f_c(T) 过高的概念剔除"""
    f_T = df[f'norm_{T}'] if f'norm_{T}' in df.columns else pd.Series(0, index=df.index)
    threshold = np.percentile(f_T[f_T > 0], percentile) if (f_T > 0).any() else float('inf')
    return df[f_T <= threshold].copy()


def run_single(panel_df, truth_df, years, T, method='momentum'):
    """对单个预测方法跑一次评估"""
    rows = []
    for _, row in panel_df.iterrows():
        pred_gc = predict_g_c(row, years, T, method=method)
        rows.append({
            'concept_id': row['concept_id'],
            'pred_g_c': pred_gc,
            'f_T': get_freq(row, T),
        })
    df_pred = pd.DataFrame(rows)

    # 排除已饱和旧热点（f_T > p80）
    f_T_vals = df_pred['f_T']
    if (f_T_vals > 0).any():
        thr = np.percentile(f_T_vals[f_T_vals > 0], 80)
        df_pred = df_pred[df_pred['f_T'] <= thr]

    # 排除 pred_g_c <= 0 的概念
    df_pred = df_pred[df_pred['pred_g_c'] > 0]
    df_pred = df_pred.sort_values('pred_g_c', ascending=False)

    pred_ids = df_pred['concept_id'].tolist()
    truth_ids = truth_df['concept_id'].tolist()
    pred_scores = df_pred['pred_g_c'].values
    truth_scores = truth_df['g_c'].values

    p10, _ = compute_metrics(pred_ids, truth_ids, k=10)
    p20, r20 = compute_metrics(pred_ids, truth_ids, k=20)
    cos_sim = compute_score_similarity(pred_scores, truth_scores, 'cosine')
    js_sim = compute_score_similarity(pred_scores, truth_scores, 'js')

    return {
        'P@10': p10, 'P@20': p20, 'R@20': r20,
        'cosine_sim': cos_sim, 'js_sim': js_sim,
        'n_pred': len(df_pred), 'n_truth': len(truth_df),
        'pred_ids': pred_ids, 'truth_ids': truth_ids,
    }


def run_e0(panel_df, truth_df, years, T, lang):
    """E0：单语实验，对比多种预测器"""
    print(f'\n=== E0 [{lang}] T={T} ===')
    results = []
    for method in ['momentum', 'log_slope', 'trend']:
        res = run_single(panel_df, truth_df, years, T, method=method)
        overlap = set(res['pred_ids'][:20]) & set(res['truth_ids'][:20])
        print(f'  [{method:10s}] P@10={res["P@10"]:.3f}  P@20={res["P@20"]:.3f}  '
              f'R@20={res["R@20"]:.3f}  cos={res["cosine_sim"]:.3f}  '
              f'overlap@20={len(overlap)}  n_pred={res["n_pred"]}')
        if method == 'momentum':
            print(f'    预测前5: {res["pred_ids"][:5]}')
            print(f'    真实前5: {res["truth_ids"][:5]}')
        results.append({
            'experiment': 'E0', 'language': lang, 'T': T,
            'method': method, **{k: v for k, v in res.items()
                                  if k not in ('pred_ids', 'truth_ids')},
        })
    return results


def run_e1(panel_df, truth_df, years, T):
    """E1：α=(1,1,1) 三语合并——等同 E0"""
    print(f'\n=== E1 T={T} α=(1,1,1) ===')
    results = []
    for method in ['momentum', 'log_slope', 'trend']:
        res = run_single(panel_df, truth_df, years, T, method=method)
        overlap = set(res['pred_ids'][:20]) & set(res['truth_ids'][:20])
        print(f'  [{method:10s}] P@10={res["P@10"]:.3f}  P@20={res["P@20"]:.3f}  '
              f'R@20={res["R@20"]:.3f}  cos={res["cosine_sim"]:.3f}  overlap@20={len(overlap)}')
        results.append({
            'experiment': 'E1', 'language': 'all', 'T': T,
            'method': method, **{k: v for k, v in res.items()
                                  if k not in ('pred_ids', 'truth_ids')},
        })
    return results


def run_e2(panel_df, truth_df, years, T, alpha_ar_vals):
    """E2：调整 α_ar，看对阿语概念排名的影响（用 momentum 方法）"""
    print(f'\n=== E2 T={T} α_ar 扫描 ===')
    results = []
    for alpha in alpha_ar_vals:
        rows = []
        for _, row in panel_df.iterrows():
            pred_gc = predict_g_c(row, years, T, method='momentum')
            is_ar = row['concept_id'].startswith('ar_')
            rows.append({
                'concept_id': row['concept_id'],
                'pred_g_c': pred_gc * (alpha if is_ar else 1.0),
                'f_T': get_freq(row, T),
            })
        df_pred = pd.DataFrame(rows)
        df_pred = df_pred[df_pred['pred_g_c'] > 0]
        df_pred = df_pred.sort_values('pred_g_c', ascending=False)
        pred_ids = df_pred['concept_id'].tolist()
        truth_ids = truth_df['concept_id'].tolist()

        p10, _ = compute_metrics(pred_ids, truth_ids, 10)
        p20, r20 = compute_metrics(pred_ids, truth_ids, 20)
        cos = compute_score_similarity(
            df_pred['pred_g_c'].values, truth_df['g_c'].values, 'cosine')
        js = compute_score_similarity(
            df_pred['pred_g_c'].values, truth_df['g_c'].values, 'js')

        print(f'  α_ar={alpha:.1f}  P@10={p10:.3f}  P@20={p20:.3f}  R@20={r20:.3f}  cos={cos:.3f}')
        results.append({
            'experiment': 'E2', 'language': 'ar', 'T': T,
            'alpha': alpha, 'method': 'momentum',
            'P@10': p10, 'P@20': p20, 'R@20': r20,
            'cosine_sim': cos, 'js_sim': js,
        })
    return results


def run_e3(panel_df, truth_df, years, T, alpha_vals):
    """E3：对称提升 zh/en（用 momentum 方法）"""
    print(f'\n=== E3 T={T} 对称升 zh/en ===')
    results = []
    for alpha in alpha_vals:
        rows = []
        for _, row in panel_df.iterrows():
            pred_gc = predict_g_c(row, years, T, method='momentum')
            rows.append({
                'concept_id': row['concept_id'],
                'pred_g_c': pred_gc * alpha,
                'f_T': get_freq(row, T),
            })
        df_pred = pd.DataFrame(rows)
        df_pred = df_pred[df_pred['pred_g_c'] > 0]
        df_pred = df_pred.sort_values('pred_g_c', ascending=False)
        pred_ids = df_pred['concept_id'].tolist()
        truth_ids = truth_df['concept_id'].tolist()

        p10, _ = compute_metrics(pred_ids, truth_ids, 10)
        p20, r20 = compute_metrics(pred_ids, truth_ids, 20)
        cos = compute_score_similarity(
            df_pred['pred_g_c'].values, truth_df['g_c'].values, 'cosine')
        js = compute_score_similarity(
            df_pred['pred_g_c'].values, truth_df['g_c'].values, 'js')

        print(f'  α={alpha:.1f}  P@10={p10:.3f}  P@20={p20:.3f}  R@20={r20:.3f}  cos={cos:.3f}')
        results.append({
            'experiment': 'E3', 'language': 'zh_en', 'T': T,
            'alpha': alpha, 'method': 'momentum',
            'P@10': p10, 'P@20': p20, 'R@20': r20,
            'cosine_sim': cos, 'js_sim': js,
        })
    return results


def main():
    base = Path(__file__).parent
    exp = base / 'exp'

    print('加载数据...')
    panel = pd.read_parquet(exp / 'panel.parquet')
    with open(exp / 'windows' / 'E_2015.json') as f:
        gt_2015 = pd.DataFrame(json.load(f))
    with open(exp / 'windows' / 'E_2020.json') as f:
        gt_2020 = pd.DataFrame(json.load(f))

    norm_cols, years = extract_years(panel)
    print(f'概念数: {len(panel)}, 年份: {min(years)}-{max(years)}')
    print(f'E_2015 真值: {len(gt_2015)}  |  E_2020 真值: {len(gt_2020)}')

    all_results = []
    all_alpha = []

    # E0
    all_results.extend(run_e0(panel, gt_2015, years, 2015, 'all'))
    all_results.extend(run_e0(panel, gt_2020, years, 2020, 'all'))

    # E1
    all_results.extend(run_e1(panel, gt_2015, years, 2015))
    all_results.extend(run_e1(panel, gt_2020, years, 2020))

    # E2
    all_alpha.extend(run_e2(panel, gt_2015, years, 2015, [0.2, 0.5, 1.0, 2.0]))
    all_alpha.extend(run_e2(panel, gt_2020, years, 2020, [0.2, 0.5, 1.0, 2.0]))

    # E3
    all_alpha.extend(run_e3(panel, gt_2015, years, 2015, [0.5, 1.0, 1.5, 2.0]))
    all_alpha.extend(run_e3(panel, gt_2020, years, 2020, [0.5, 1.0, 1.5, 2.0]))

    # 保存
    df_r = pd.DataFrame(all_results)
    df_r.to_csv(exp / 'results.csv', index=False)
    df_a = pd.DataFrame(all_alpha)
    df_a.to_csv(exp / 'results_alpha.csv', index=False)
    print(f'\n结果已保存到 {exp}/results.csv 和 results_alpha.csv')

    print('\n=== E0/E1 ===')
    print(df_r.to_string(index=False))
    print('\n=== E2/E3 ===')
    print(df_a.to_string(index=False))


if __name__ == '__main__':
    main()