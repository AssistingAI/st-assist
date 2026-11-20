#!/usr/bin/env python3
"""fetch_risk_flags.py — 从巨潮资讯网按公司定向拉取ST公告风险/纾困信号

数据源: https://www.cninfo.com.cn/new/hisAnnouncement/query (POST, 公司定向查询)
方法: 每家ST公司定向拉取近24个月全部公告标题(翻页+去重) → 本地关键词分类进12桶
输出: st_risk_flags.json
  {code: {
    "investigation": [...],   # B1 立案调查公告
    "penalty": [...],          # B1/B3 行政处罚公告(2026-08-30起并入B1: 处罚落地=违法实锤)
    "warning": [...],          # B3 警示函/监管函
    "audit_adverse": [...],    # B2 无法表示意见/否定意见(最重)
    "audit_qualified": [...],  # B2 保留意见
    "audit_emphasis": [...],   # B2 带强调事项/持续经营/非标准(轻)
    "freeze": [...],           # H1 股份冻结
    "consume_limit": [...],    # H1 限制消费/限高
    "restructuring": [...],    # F2 重整(分阶段)
    "asset_sale": [...],       # F2 重大资产出售/重组
    "debt_waiver": [...],      # F2 债务豁免/债务重组
    "donation": [...]          # F2 资产赠与/捐赠
  }}

历史(2026-08-30方案切换): 旧版用全市场关键词搜索, 但巨潮关键词大窗口翻页存在
重复返回+截断bug(5页请求500条实际唯一仅~30条, 元道立案公告永远翻不到)；
公司定向查询(stock=code,orgId)翻页正常且覆盖全量, 故弃关键词方案改定向。
orgId 来源: https://www.cninfo.com.cn/new/data/szse_stock.json (巨潮官方股票映射)
注: 每条公告记录 {title, date}。北交所股票不在巨潮沪深库中, 走规则降级。
"""
import json, os, re, sys, time, random, io
import urllib.request, urllib.parse
import http.cookiejar
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
PDF_CACHE = os.path.join(BASE, '.pdf_cache')  # 公告PDF缓存(避免重复下载)

# ── 配置 ──────────────────────────────────────────
MONTHS_BACK = 24
PAGE_SIZE = 30                 # 巨潮服务端钳制: 定向查询pageSize最大30
MAX_PAGES_PER_STOCK = 20       # 每公司最多20页(600条公告)防失控
SLEEP_RANGE = (0.6, 1.2)

API_URL = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
ORG_URL = 'https://www.cninfo.com.cn/new/data/szse_stock.json'


def make_opener():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open('https://www.cninfo.com.cn', timeout=15)  # 领cookie
    return op


def strip_tags(text):
    return re.sub(r'<[^>]+>', '', text or '')


def ts_to_date(ts_ms):
    if not ts_ms:
        return ''
    return datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d')


# ── 公司定向拉取 ──────────────────────────────────
def fetch_company(opener, code, org_id, se_date):
    """定向拉取单家公司窗口内全部公告(翻页+announcementId去重)"""
    all_anns, seen_ids = [], set()
    page = 1
    while page <= MAX_PAGES_PER_STOCK:
        data = urllib.parse.urlencode({
            'pageNum': str(page), 'pageSize': str(PAGE_SIZE),
            'column': 'szse', 'tabName': 'fulltext',
            'stock': f'{code},{org_id}', 'searchkey': '',
            'seDate': se_date, 'isHLtitle': 'true',
        }).encode()
        try:
            r = opener.open(urllib.request.Request(API_URL, data=data, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.cninfo.com.cn/new/fulltextSearch',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            }), timeout=20)
            j = json.loads(r.read().decode('utf-8'))
        except Exception as e:
            print(f'    第{page}页失败({e}), 重试一次...')
            time.sleep(5)
            try:
                r = opener.open(urllib.request.Request(API_URL, data=data, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': 'https://www.cninfo.com.cn/new/fulltextSearch',
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                }), timeout=20)
                j = json.loads(r.read().decode('utf-8'))
            except Exception:
                break
        anns = j.get('announcements') or []
        new = [a for a in anns if a.get('announcementId') and a['announcementId'] not in seen_ids]
        for a in anns:
            if a.get('announcementId'):
                seen_ids.add(a['announcementId'])
        all_anns.extend(new)
        if not new or not anns:  # 翻页重复或到底
            break
        page += 1
        time.sleep(random.uniform(*SLEEP_RANGE))
    return all_anns


# ── 标题分类(替代旧版kw+title双因子分类, 定向方案无kw) ──
def classify_title(title):
    t = title
    # B2 审计意见（含内控审计：v2.4起内控否定/无法表示同样归audit_adverse）
    if '无法表示意见' in t or '否定意见' in t:
        return 'audit_adverse'
    if '保留意见' in t:
        return 'audit_qualified'
    if '非标准' in t and ('审计' in t or '意见' in t or '专项说明' in t):
        return 'audit_emphasis'
    # B1 立案/处罚
    if '立案' in t and ('调查' in t or '证监会' in t or '进展' in t or '告知书' in t or '决定书' in t or '涉嫌' in t):
        return 'investigation'
    if '处罚' in t and ('决定书' in t or '事先告知' in t or '行政处罚' in t):
        return 'penalty'
    # B3 警示
    if '警示函' in t or '监管函' in t:
        return 'warning'
    # F2 纾困/重组
    if '重整' in t:
        return 'restructuring'
    if ('重大资产' in t and ('出售' in t or '重组' in t or '购买' in t)) or '资产出售' in t:
        return 'asset_sale'
    if ('豁免' in t and '债务' in t) or '债务重组' in t:
        return 'debt_waiver'
    if '赠与' in t or '捐赠' in t or '无偿' in t:
        return 'donation'
    # H1 司法
    if '冻结' in t:
        return 'freeze'
    if '限制消费' in t or '限高' in t:
        return 'consume_limit'
    return None


BUCKETS = ['investigation', 'penalty', 'warning', 'audit_adverse',
           'audit_qualified', 'audit_emphasis', 'freeze', 'consume_limit',
           'restructuring', 'asset_sale', 'debt_waiver', 'donation',
           # v2.4 新增桶：内控审计意见 / 中院重整立案 / 现金捐赠(带金额解析)
           'ic_adverse', 'court_restruct', 'cash_donation']

RESTRUCT_STAGE = re.compile(r'计划(执行|获|批|通过|获准|获法院)|裁定批准|执行进展|重整完成|终结')
# 中级法院重整立案（法院受理/裁定重整，且明确中级法院）
COURT_RESTRUCT = re.compile(r'(中级(人民)?法院|中院).{0,30}(重整|受理|立案)|(重整|受理).{0,30}(中级(人民)?法院|中院)')
# 现金捐赠金额（支持千分位逗号 12,000万元 / 2亿元 / 5000万）
DONATION_AMT = re.compile(r'(\d[\d,]*\.?\d*)\s*(亿元|亿|万元|万)')
# 正文金额提取：优先取"赠与/捐赠/无偿赠予...金额"同句的数字
DONATION_CTX = re.compile(r'(?:赠与|捐赠|赠予|无偿|现金)[^。；\n]{0,40}?' + DONATION_AMT.pattern)


def _amt_to_yi(num_str, unit):
    v = float(num_str.replace(',', ''))
    return v if '亿' in unit else v / 10000.0


def parse_donation_yi(title_or_text):
    """现金捐赠金额（亿元）；支持千分位逗号与'亿/万'单位。无法解析返回None。"""
    s = title_or_text or ''
    # 正文优先带上下文的金额
    m = DONATION_CTX.search(s)
    if m:
        return _amt_to_yi(m.group(1), m.group(2))
    m = DONATION_AMT.search(s)
    if not m:
        return None
    return _amt_to_yi(m.group(1), m.group(2))


# ── 公告PDF正文解析（F1现金捐赠金额 / 中院重整立案校验）──
def download_pdf(adjunct_url, opener=None):
    """下载巨潮公告PDF，带本地缓存；返回bytes或None。adjunct_url 形如 finalpage/2026-11-20/xxx.PDF"""
    if not adjunct_url:
        return None
    os.makedirs(PDF_CACHE, exist_ok=True)
    fname = os.path.basename(adjunct_url)
    m = re.search(r'(\d{4}-\d{2}-\d{2})', adjunct_url)
    cache = os.path.join(PDF_CACHE, (m.group(1) + '_' if m else '') + fname)
    if os.path.exists(cache) and os.path.getsize(cache) > 1000:
        with open(cache, 'rb') as f:
            return f.read()
    url = 'https://static.cninfo.com.cn/' + adjunct_url
    try:
        op = opener or make_opener()
        content = op.open(urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.cninfo.com.cn/',
        }), timeout=25).read()
        if content[:4] == b'%PDF':
            with open(cache, 'wb') as f:
                f.write(content)
            return content
    except Exception as e:
        print(f'    [PDF] 下载失败 {fname}: {e}', flush=True)
    return None


def pdf_text(pdf_bytes, max_pages=6):
    """pdfplumber 提取PDF正文文本（前max_pages页，金额/法院表述一般在前几页）"""
    if not pdf_bytes:
        return ''
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return '\n'.join((p.extract_text() or '') for p in pdf.pages[:max_pages])
    except Exception as e:
        print(f'    [PDF] 解析失败: {e}', flush=True)
        return ''


COURT_ACCEPT = re.compile(r'(受理|裁定|立案).{0,25}(重整|破产重整)|(重整|破产重整).{0,25}(受理|裁定|立案)|法院.{0,40}(裁定|受理)')
COURT_REJECT = re.compile(r'不予受理|尚未受理|未获受理|驳回.{0,10}重整|裁定驳回')


def verify_restruct_text(text):
    """校验中院重整公告正文：含法院受理/裁定重整表述 且 无'不予受理/驳回'→True。
    保守口径：正文只要出现明确否决表述即回滚（避免F1虚增），无法判定(None)维持标题结论。"""
    if not text:
        return None
    if COURT_REJECT.search(text):
        return False
    return bool(COURT_ACCEPT.search(text))


def load_org_map(opener):
    """巨潮官方股票映射: code -> orgId"""
    r = opener.open(urllib.request.Request(ORG_URL, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }), timeout=20)
    j = json.loads(r.read().decode('utf-8'))
    return {x['code']: x['orgId'] for x in (j.get('stockList') or []) if x.get('code') and x.get('orgId')}


def _enrich_one(task):
    """解析单条公告PDF：type=donation提取金额 / type=restruct校验中院立案。返回统计增量dict"""
    code, idx, bucket, rec = task
    out = {'pdf_ok': 0, 'amt_found': 0, 'restruct_confirmed': 0, 'restruct_rejected': 0, 'pdf_fail': 0}
    content = download_pdf(rec.get('adjunctUrl'))
    if not content:
        out['pdf_fail'] += 1
        return out
    out['pdf_ok'] += 1
    text = pdf_text(content)
    if bucket == 'cash_donation':
        amt = parse_donation_yi(text)
        rec['amount_yi'] = amt          # None=正文也无金额，保守不给满分
        rec['pdf_amount'] = True
        rec['needs_pdf'] = False
        if amt is not None:
            out['amt_found'] += 1
            rec['_pdf_excerpt'] = next((l.strip()[:80] for l in text.split('\n')
                                        if re.search(r'\d[\d,]*\s*(亿|万)', l)
                                        and ('赠' in l or '捐' in l)), '')[:80]
    elif bucket == 'court_restruct':
        verdict = verify_restruct_text(text)
        rec['pdf_verified'] = verdict
        rec['needs_pdf'] = False
        if verdict is True:
            out['restruct_confirmed'] += 1
        elif verdict is False:
            out['restruct_rejected'] += 1
    return out


def enrich_pdfs(flags, org_map=None, max_workers=3):
    """遍历flags中needs_pdf现金捐赠/中院重整记录，下载PDF解析回填。返回统计。"""
    tasks = []
    for code, buckets in flags.items():
        for idx, rec in enumerate(buckets.get('cash_donation', [])):
            if rec.get('needs_pdf') and rec.get('adjunctUrl'):
                tasks.append((code, idx, 'cash_donation', rec))
        for idx, rec in enumerate(buckets.get('court_restruct', [])):
            if rec.get('needs_pdf') and rec.get('adjunctUrl'):
                tasks.append((code, idx, 'court_restruct', rec))
    total = {'pdf_ok': 0, 'amt_found': 0, 'restruct_confirmed': 0, 'restruct_rejected': 0, 'pdf_fail': 0}
    if not tasks:
        print('  [PDF解析] 无待解析公告（记录已含金额/PDF字段或历史数据无URL）')
        return total
    print(f'  [PDF解析] 待解析 {len(tasks)} 条（现金捐赠+中院重整），下载正文...', flush=True)
    t0 = time.time()
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_enrich_one, t) for t in tasks]
        for fut in as_completed(futs):
            try:
                inc = fut.result()
                for k, v in inc.items():
                    total[k] += v
            except Exception as e:
                total['pdf_fail'] += 1
                print(f'    [PDF解析] 线程异常: {e}', flush=True)
    print(f'  [PDF解析] 完成({time.time()-t0:.1f}s): 成功{total["pdf_ok"]}/失败{total["pdf_fail"]} | '
          f'捐赠金额命中{total["amt_found"]} | 中院重整确认{total["restruct_confirmed"]}/驳回{total["restruct_rejected"]}', flush=True)
    return total


def main():
    # 加载ST名单
    with open(os.path.join(BASE, 'st_names.json'), encoding='utf-8') as f:
        name_map = json.load(f)
    st_codes = sorted(name_map.keys())
    print(f'[1/3] ST名单: {len(st_codes)} 只')

    # 日期窗口: 近24个月
    today = datetime.now()
    start = today - timedelta(days=MONTHS_BACK * 30)
    se_date = f"{start.strftime('%Y-%m-%d')}~{today.strftime('%Y-%m-%d')}"
    print(f'[2/3] 窗口: {se_date}（公司定向查询）')

    opener = make_opener()
    org_map = load_org_map(opener)
    print(f'      orgId映射: {len(org_map)} 只')

    def process_one(code):
        """单公司采集+分桶（线程内独立opener，返回 code -> buckets dict）"""
        org_id = org_map.get(code)
        if not org_id:
            return code, None, 0  # 北交所等不在巨潮沪深库
        my_op = make_opener()  # 每线程独立cookie
        anns = fetch_company(my_op, code, org_id, se_date)
        buckets = {b: [] for b in BUCKETS}
        n_hit = 0
        for a in anns:
            title = strip_tags(a.get('announcementTitle', ''))
            bucket = classify_title(title)
            if bucket is None:
                continue
            date = ts_to_date(a.get('announcementTime'))
            rec = {'title': title, 'date': date}
            # 保存PDF溯源字段（供F1现金捐赠金额/中院重整正文解析）
            if a.get('announcementId'):
                rec['announcementId'] = a['announcementId']
            if a.get('adjunctUrl'):
                rec['adjunctUrl'] = a['adjunctUrl']
            if bucket == 'restructuring':
                rec['stage'] = 'exec' if RESTRUCT_STAGE.search(title) else 'early'
            buckets[bucket].append(rec)
            n_hit += 1
            # ── v2.4 F1附加 / B2内控：同一公告并行入新桶 ──
            if bucket == 'restructuring' and '不予受理' not in title and (
                COURT_RESTRUCT.search(title)
                or ('法院' in title and '受理' in title and '重整' in title)
            ):
                crec = dict(rec)
                crec['needs_pdf'] = True  # 正文校验中院立案(可回滚误命中)
                buckets['court_restruct'].append(crec)
            if bucket == 'donation' and ('现金' in title or '现' in title):
                amt = parse_donation_yi(title)  # 标题级(支持千分位)
                drec = dict(rec)
                drec['amount_yi'] = amt
                drec['needs_pdf'] = amt is None
                buckets['cash_donation'].append(drec)
            if bucket == 'audit_adverse' and ('内控' in title or '内部控制' in title):
                buckets['ic_adverse'].append(dict(rec))
        return code, buckets, len(anns)

    flags = {c: {b: [] for b in BUCKETS} for c in st_codes}
    stats = {}
    t0 = time.time()
    done = 0
    MAX_WORKERS = 4  # 巨潮并发度：4线程兼顾速度与频率友好
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(process_one, c): c for c in st_codes}
        for fut in as_completed(futs):
            code, buckets, n_anns = fut.result()
            done += 1
            if buckets is not None:
                flags[code] = buckets
                for b, items in buckets.items():
                    stats[b] = stats.get(b, 0) + len(items)
            if done % 20 == 0 or done == len(st_codes):
                el = time.time() - t0
                print(f'  [{done}/{len(st_codes)}] 已用{el/60:.1f}分钟 | 累计命中{sum(stats.values())}条', flush=True)

    # ── [NEW] PDF正文定向解析：F1现金捐赠金额 + 中院重整立案校验 ──
    pdf_stat = enrich_pdfs(flags, org_map)

    # 写出
    out = {
        'meta': {
            'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'window': se_date,
            'method': 'company_targeted',  # 公司定向查询(旧keyword_search方案2026-08-30废弃)
            'bucket_stats': stats,
            'pdf_enrich': pdf_stat,  # F1公告正文解析统计
        },
        'flags': flags,
    }
    path = os.path.join(BASE, 'st_risk_flags.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'[3/3] 已写入 {path}')
    print(f'完成! 桶统计: {json.dumps(stats, ensure_ascii=False)}')
    print(f'有信号公司数: {sum(1 for v in flags.values() if any(v.values()))} / {len(st_codes)}')


if __name__ == '__main__':
    main()
