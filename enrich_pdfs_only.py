#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定向补齐 st_risk_flags.json 里 needs_pdf 公告的正文解析（不重采全量）

用途：全量采集已存 adjunctUrl，但当时 PDF 下载被沙箱拦截(403)。本脚本单独重跑
      29条（现金捐赠11 + 中院重整18）的 PDF 下载+正文解析，回填 amount_yi / pdf_verified。
用法：python enrich_pdfs_only.py
"""
import json, os, sys, time
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import fetch_risk_flags as F

PATH = os.path.join(BASE, 'st_risk_flags.json')


def main():
    with open(PATH, encoding='utf-8') as f:
        data = json.load(f)
    flags = data['flags']

    tasks = []
    for code, buckets in flags.items():
        for idx, rec in enumerate(buckets.get('cash_donation', [])):
            if rec.get('needs_pdf') and rec.get('adjunctUrl'):
                tasks.append((code, idx, 'cash_donation', rec))
        for idx, rec in enumerate(buckets.get('court_restruct', [])):
            if rec.get('needs_pdf') and rec.get('adjunctUrl'):
                tasks.append((code, idx, 'court_restruct', rec))
    print(f'待解析 {len(tasks)} 条 (现金捐赠+中院重整)', flush=True)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    total = {'pdf_ok': 0, 'amt_found': 0, 'restruct_confirmed': 0,
             'restruct_rejected': 0, 'pdf_fail': 0}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(F._enrich_one, t) for t in tasks]
        for fut in as_completed(futs):
            try:
                inc = fut.result()
                for k, v in inc.items():
                    total[k] += v
            except Exception as e:
                total['pdf_fail'] += 1
                print(f'  线程异常: {e}', flush=True)
    print(f'完成({time.time()-t0:.1f}s): {total}', flush=True)

    data.setdefault('meta', {})['pdf_enrich'] = total
    with open(PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    # 明细
    print('\n=== 现金捐赠金额解析明细 ===')
    for code, buckets in flags.items():
        for rec in buckets.get('cash_donation', []):
            if rec.get('amount_yi') is not None or rec.get('pdf_amount'):
                print(f"  {code}  {rec.get('amount_yi')}亿  {rec.get('_pdf_excerpt','')[:50]}  {rec['title'][:30]}")
    print('\n=== 中院重整正文校验 ===')
    for code, buckets in flags.items():
        for rec in buckets.get('court_restruct', []):
            if 'pdf_verified' in rec:
                print(f"  {code}  verified={rec['pdf_verified']}  {rec['title'][:45]}")


if __name__ == '__main__':
    main()
