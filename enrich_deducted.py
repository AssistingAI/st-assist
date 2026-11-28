#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定向补齐 st_financials.json 的 deducted_profit（扣非净利润）

背景：fetch_financials.py 的扣非走同花顺 stock_financial_abstract_ths，
      在国内网络/沙箱下 basic.10jqka.com.cn 常被拦导致全缺失(0/199)。
      本脚本单独抓扣非并回填，不改其他财务字段。
口径：动态取最新报告期（如2026-09-30三季报）；若最新一期扣非为空，
      往前找最近有值的一期。单位统一为元。
用法：python enrich_deducted.py
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import akshare as ak

FIN_PATH = os.path.join(BASE, 'st_financials.json')
MAX_WORKERS = 6


def parse_cn(v):
    if v is None or v is False or str(v).strip() in ('', 'False', 'None'):
        return None
    try:
        s = str(v).strip()
        if '亿' in s:
            return float(s.replace('亿', '')) * 1e8
        if '万' in s:
            return float(s.replace('万', '')) * 1e4
        return float(s)
    except (ValueError, TypeError):
        return None


def fetch_one(code):
    try:
        df = ak.stock_financial_abstract_ths(symbol=code, indicator='按报告期')
        if df is None or df.empty or '扣非净利润' not in df.columns:
            return code, None, None
        df = df.sort_values('报告期', ascending=False)
        for _, r in df.iterrows():
            v = parse_cn(r.get('扣非净利润'))
            if v is not None:
                return code, v, r.get('报告期')
        return code, None, None
    except Exception:
        return code, None, None


def main():
    d = json.load(open(FIN_PATH, encoding='utf-8'))
    data = d['data']
    codes = list(data.keys())
    print(f'补齐扣非净利润: {len(codes)} 只', flush=True)
    t0 = time.time()
    ok = 0
    periods = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_one, c): c for c in codes}
        for i, fut in enumerate(as_completed(futs), 1):
            code, val, period = fut.result()
            if val is not None:
                data[code]['deducted_profit'] = val
                ok += 1
                periods[period] = periods.get(period, 0) + 1
            if i % 50 == 0:
                print(f'  {i}/{len(codes)} 成功{ok}', flush=True)
    d['deducted_fetch_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(FIN_PATH, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f'完成({time.time()-t0:.1f}s): {ok}/{len(codes)} 只扣非回填', flush=True)
    print('报告期分布:', dict(sorted(periods.items(), reverse=True)), flush=True)


if __name__ == '__main__':
    main()
