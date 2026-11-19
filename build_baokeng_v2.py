#!/usr/bin/env python3
"""ST保壳评分系统V2 批量构建管道 — v2.4 十主维度100分+F1附加10分=110满分（2026-11-19重构）

阶段3「分头解耦」（2026-08-29）：权重/档位/闸门/评级全部外置至 score_config_v2.json，
改配置不改代码；SHELL_BASE继续从shell-fee-base单源库动态读取。

【2026-08-30 单源改造】评分核心已抽取至 score_v2.py（load_context + score_v2），
本管道与会员个股深度报告共用同一评分实现——榜单分数=个股报告分数。
批量fetch管道不动；改评分逻辑只改 score_v2.py，改权重只改 score_config_v2.json。

设计哲学：财务健康度打分 → 退市概率打分（违约模型）
  维度=退市通道，权重=近5年176家退市案例实证贡献度
  股东实力（实控人性质）=调节变量

老Z定稿六处调整（2026-08-28）：
  C1面值 10→6 | B2审计 8→12（与S1并列第一权重）| C2壳价值规则反转（市值越低于壳基准分越高）
  A2改"扣非主营业务收入"口径 | F2重组 8→6 | A3扣非 4→6；总分仍=100

老Z 12维重构（2026-09-02，config v2.3）：
  取消F1经营改善趋势4分 → A1净资产+2分(10→12)、C2壳价值+2分(8→10)；F2重组更名F1；总分仍=100

老Z v2.4重构（2026-11-19）：12维→10主维度+F1附加；删H1并入B1；D1现金流改A4负债；
F1改附加10分(中院重整立案或现金捐赠≥1000万)；B1 10→12；C1 6→8；A3 6→8；评级阈值按110分制上调。

| 维度 | 满分 | 数据源 |
|------|------|--------|
| A1 净资产充裕度  | 12 | AkShare东方财富 |
| A2 扣非主营收入  | 12 | AkShare东方财富（F10主营构成口径） |
| A3 扣非盈利      | 8  | AkShare同花顺 |
| A4 负债规模/率   | 8  | AkShare资产负债表（>10亿或负债率>90%→0） |
| C1 面值距离      | 8  | 腾讯实时价格 |
| C2 壳价值锚定    | 10 | 腾讯市值（壳基准33.81亿，反转计分） |
| S1 实控人性质    | 12 | 东财F10 + 前十大股东 |
| S2 质押与控制权  | 6  | AkShare质押 + 巨潮冻结 |
| B1 立案/造假+司法| 12 | 巨潮公告（H1司法并入作扣分） |
| B2 审计意见      | 12 | 巨潮公告（含内控否定/无法表示→0） |
| 主分合计         | 100 | |
| F1 重组纾困附加  | 10 | 巨潮公告（中院重整立案或现金捐赠≥1000万→10） |
| 总分上限         | 110 | 主分100 + 附加10 |

联动规则：涉造假立案 → S1封顶4；C1=0/B2=0主分封顶55、B1=0封顶33（110分制）；F1附加不受闸门
评级（分数越高=退市风险越低）：A(>77) B(56-77) C(33-55) D(≤33)
"""
import json
import os
from datetime import datetime

from score_v2 import load_context, score_v2

BASE = os.path.dirname(os.path.abspath(__file__))

ctx = load_context()
REPORT_DATE = ctx['report_date']
REPORT_LABEL = f"{REPORT_DATE[:4]}年{int(REPORT_DATE[4:6])}月报" if REPORT_DATE and len(REPORT_DATE) == 8 else '未知报告期'

codes = list(ctx['name_map'].keys())

scores = [score_v2(c, ctx) for c in codes]
scores.sort(key=lambda x: x['total'], reverse=True)
for i, r in enumerate(scores, 1):
    r['rank'] = i

payload = {
    'meta': {
        'system': 'ST保壳评分系统V2 v2.4（十主维度100分+F1附加10分=110满分，2026-11-19重构）',
        'philosophy': '退市概率打分：维度=退市通道，权重=5年176家退市案例实证贡献度',
        'dims': 'A1净资产12/A2扣非主营12/A3扣非盈利8/A4负债8(负债>10亿或负债率>90%→0)/'
                'C1面值8/C2壳价值10(反转,基准33.81亿)/S1实控人12/S2质押6/'
                'B1立案造假12(含H1司法扣分)/B2审计12(含内控否定) + F1重组纾困附加10(中院重整立案或现金捐赠≥1000万)',
        'levels': 'A(>77) B(56-77) C(33-55) D(≤33) 按110分制；主分100+附加10；分数越高=退市风险越低；'
                  '联动规则：C1≤1时C2降档；涉造假立案S1封顶4；H1司法并入B1扣分',
        'config': '权重/档位/闸门/评级外置score_config_v2.json(v2.4，2026-11-19 12→10主维度+F1附加重构)；'
                  '评分核心单源自score_v2.py(与个股报告共用)',
        'report_date': REPORT_DATE,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'n': len(scores),
    },
    'data': scores,
}
with open(os.path.join(BASE, 'st_scores_v2.json'), 'w', encoding='utf-8') as f:
    json.dump(payload, f, ensure_ascii=False, indent=1)

# ── 摘要 ──
from collections import Counter
lv = Counter(r['level'] for r in scores)
print(f'[V2] 完成：{len(scores)}家 → st_scores_v2.json')
print('[V2] 评级分布：', dict(lv))
avg = sum(r['total'] for r in scores) / len(scores)
print(f'[V2] 全市场均分 {avg:.1f}')

soe = [r for r in scores if r['controller_cat'] in ('央企', '省级国资', '市县国资', '国资(未分层)')]
poa = [r for r in scores if r['controller_cat'].startswith('民企')]
if soe:
    print(f'[V2] 国资壳({len(soe)}家)均分 {sum(r["total"] for r in soe)/len(soe):.1f}')
if poa:
    print(f'[V2] 民企壳({len(poa)}家)均分 {sum(r["total"] for r in poa)/len(poa):.1f}')

print('\n[V2] Top 10：')
for r in scores[:10]:
    print(f"  {r['rank']:>3} {r['code']} {r['name']:<10} {r['total']:>3} {r['level']} "
          f"[V1:{r['v1_total']}/{r['v1_level']}] {r['controller_cat']}")
print('\n[V2] Bottom 10：')
for r in scores[-10:]:
    print(f"  {r['rank']:>3} {r['code']} {r['name']:<10} {r['total']:>3} {r['level']} "
          f"[V1:{r['v1_total']}/{r['v1_level']}] {r['note'][:30]}")

mg = next((r for r in scores if r['code'] == '600543'), None)
if mg:
    print(f"\n[V2] 莫高验算：{mg['total']}分/{mg['level']}（V1 {mg['v1_total']}/{mg['v1_level']}）")
    for k in ('A1', 'A2', 'A3', 'A4', 'C1', 'C2', 'S1', 'S2', 'B1', 'B2', 'F1'):
        print(f'    {k}={mg[k]}', end='')
    print()

# 升降榜
deltas = [(r, (r['total'] - (r['v1_total'] or 0))) for r in scores]
up = sorted(deltas, key=lambda x: -x[1])[:5]
print('\n[V2] 相对V1升幅Top5：')
for r, d in up:
    print(f'  {r["code"]} {r["name"]:<10} {r["v1_total"]}→{r["total"]} (+{d}) {r["controller_cat"]}')
