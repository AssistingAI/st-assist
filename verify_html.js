// 铁律一验证：V2.4（唯一口径）RAW求和+通道封顶须与total一致
// RAW 结构(11字段,纯数据): [code,name,type,board,reason, delisted(5), note(6), mkt_cap(7), mkt_str(8), prev_close(9), flags(10)]
// V2RAW 结构(v2.4): [code,name,type,board, A1..B2(10主维度 idx4-13), F1附加(14),
//                    base主分(15), delisted(16), note(17), controller(18), controller_cat(19), total(20)]
const fs = require('fs');
const html = fs.readFileSync('baokeng-rank.html', 'utf8');

function extractArray(name) {
  const re = new RegExp('const ' + name + ' = (\\[[\\s\\S]*?\\n\\]);');
  const m = html.match(re);
  if (!m) throw new Error(name + ' not found');
  return JSON.parse(m[1].replace(/,(\s*\n\])/, '$1'));
}

const RAW = extractArray('RAW');
const V2RAW = extractArray('V2RAW');

// v2.4 总分计算：10主维度求和→闸门封顶→+F1附加
function calc(r) {
  let base = r.slice(4, 14).reduce((a, b) => a + b, 0);  // A1..B2 十主维度
  if (r[8] === 0) base = Math.min(base, 55);   // C1=0 (idx8)
  if (r[13] === 0) base = Math.min(base, 55);  // B2=0 (idx13)
  if (r[12] === 0) base = Math.min(base, 33);  // B1=0 (idx12)
  return base + r[14];  // +F1附加
}
function lvl(s) { return s > 77 ? 'A' : s > 56 ? 'B' : s > 33 ? 'C' : 'D'; }

let bad1 = 0, bad2 = 0, mismatch = 0;
RAW.forEach(r => {
  if (r.length !== 11) { bad1++; console.log('RAW bad row len', r[0], r.length); }
  if (typeof r[5] !== 'boolean') { bad1++; console.log('RAW delisted not bool', r[0]); }
});
V2RAW.forEach(r => {
  if (r.length !== 21) { bad1++; console.log('V2 bad row len', r[0], r.length); }
  const s = calc(r);
  const t = r[20];
  if (s !== t) { bad2++; console.log('V2 sum!=total', r[0], 'sum=', s, 'total=', t); }
  let chkBase = r.slice(4, 14).reduce((a, b) => a + b, 0);
  if (r[8] === 0) chkBase = Math.min(chkBase, 55);
  if (r[13] === 0) chkBase = Math.min(chkBase, 55);
  if (r[12] === 0) chkBase = Math.min(chkBase, 33);
  if (r[15] !== chkBase) { console.log('V2 base mismatch', r[0], 'base field=', r[15], 'calc=', chkBase); }
});
const c1 = new Set(RAW.map(r => r[0])), c2 = new Set(V2RAW.map(r => r[0]));
c1.forEach(c => { if (!c2.has(c)) mismatch++; });
console.log('RAW rows:', RAW.length, '| V2 rows:', V2RAW.length, '| V2 row len:', V2RAW[0].length);
console.log('RAW bad rows:', bad1, '| V2 sum!=total:', bad2, '| V2 missing codes:', mismatch);

// 统计卡等级分布（V2口径、非退市）
const lv = { A: 0, B: 0, C: 0, D: 0 };
V2RAW.forEach(r => {
  if (r[16]) return;
  lv[lvl(calc(r))]++;
});
console.log('V2 active level dist:', JSON.stringify(lv));

// F1附加命中统计
const bonusHit = V2RAW.filter(r => r[14] > 0).length;
console.log('F1 bonus hits:', bonusHit, '/', V2RAW.length);

// 莫高原样核对
const mg = V2RAW.find(r => r[0] === '600543');
const mgs = calc(mg);
console.log('莫高V2 sum=' + mgs, '| total=' + mg[20], '| level=' + lvl(mgs),
  '| base=' + mg[15], '| F1=' + mg[14], '| 实控人=' + mg[18], '| 分类=' + mg[19]);

// JS 语法检查
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
fs.writeFileSync('_check.js', script);
try {
  require('child_process').execSync('node --check _check.js', { stdio: 'pipe' });
  console.log('JS syntax: OK');
} catch (e) {
  console.log('JS syntax ERROR:', e.stderr ? e.stderr.toString() : e.message);
}
