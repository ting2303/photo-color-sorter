# -*- coding: utf-8 -*-
"""準確率評估：讀資料夾裡的 labels.csv（tools/label_tool.py 產生，或自己用 Excel 填），
跑一次分析，輸出膚色／整體／人數的準確率、混淆矩陣、錯最多的照片，存成 tools/eval_報告_時間.md。

用法：
  python tools/evaluate.py 資料夾1 [資料夾2 ...] [--stage standard|pale] [--half A|B] [--name 備註]
  python tools/evaluate.py 資料夾 --from-csv 匯出的分析.csv     # 不重新分析，直接用匯出的 CSV 計分

labels.csv 欄位：檔名,膚色,整體,人數,備註。顏色用 紅 橙 黃 綠 青 藍 紫 粉 白 暗 無；空白的欄位不計分。
檔名比對會忽略本工具加的顏色前綴與副檔名，所以改過名的照片也對得上。
--half：依檔名固定分成兩半（A／B），一半拿來調參數、另一半驗證，避免只是記住答案。
"""
import argparse
import csv
import datetime
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import photo_color_sorter as pcs  # noqa: E402

ORDER = ['白', '紅', '橙', '黃', '綠', '青', '藍', '紫', '粉', '暗', '無']
HERE = os.path.dirname(os.path.abspath(__file__))


def key_of(name):
    """比對用的鍵：去掉顏色前綴、副檔名，不分大小寫"""
    return pcs.file_stem(pcs.strip_prefix(os.path.basename(name))).lower()


def in_half(name, half):
    if not half:
        return True
    h = int(hashlib.md5(key_of(name).encode('utf-8')).hexdigest(), 16) % 2
    return h == (0 if half.upper() == 'A' else 1)


def read_labels(folder):
    path = os.path.join(folder, 'labels.csv')
    if not os.path.exists(path):
        raise FileNotFoundError('找不到 %s（請先用 tools/label_tool.py 標註）' % path)
    with open(path, newline='', encoding='utf-8-sig') as fp:
        rows = [r for r in csv.DictReader(fp) if (r.get('檔名') or '').strip()]
    for r in rows:
        for k in ('膚色', '整體'):
            v = (r.get(k) or '').strip()
            if v and v not in ORDER:
                raise ValueError('%s 的 %s 是「%s」，不是 %s 其中之一' % (r['檔名'], k, v, ' '.join(ORDER)))
    return rows


def predict_by_analysis(folder, wanted, stage):
    """只分析有標註的照片（快很多）；回傳 {鍵: {'膚色', '整體', '人數', '檔名'}}"""
    groups = [g for g in pcs.collect_groups(folder) if key_of(g['source']) in wanted]
    res = pcs.run_analysis(groups, stage=stage)
    out = {}
    for r in res:
        k = key_of(r['source'])
        if r.get('error'):
            out[k] = {'檔名': r['source'], 'error': r['error']}
        else:
            out[k] = {'檔名': r['source'], '膚色': pcs.label(r['skin']), '整體': pcs.label(r['main']),
                      '人數': r['faces'], '整體比例': r['main_ratio']}
    return out


def predict_from_csv(path):
    out = {}
    with open(path, newline='', encoding='utf-8-sig') as fp:
        for r in csv.DictReader(fp):
            name = (r.get('檔名') or '').lstrip("'")
            if not name or r.get('錯誤'):
                continue
            faces = r.get('人數', r.get('臉數', ''))
            out[key_of(name)] = {'檔名': name, '膚色': r.get('膚色', ''), '整體': r.get('整體', ''),
                                 '人數': int(faces) if str(faces).isdigit() else None}
    return out


def score(labels, preds):
    """回傳統計結果 dict"""
    s = {'n': 0, 'missing': [], 'errors_read': [], 'skin': [0, 0], 'main': [0, 0], 'people': [0, 0, 0, 0.0],
         'cm_skin': {}, 'cm_main': {}, 'people_over': 0, 'people_under': 0, 'wrong': []}
    for lab in labels:
        k = key_of(lab['檔名'])
        p = preds.get(k)
        if p is None:
            s['missing'].append(lab['檔名'])
            continue
        if p.get('error'):
            s['errors_read'].append((lab['檔名'], p['error']))
            continue
        s['n'] += 1
        wrong = []
        for f, key in (('膚色', 'skin'), ('整體', 'main')):
            truth = (lab.get(f) or '').strip()
            if not truth:
                continue
            s[key][1] += 1
            cm = s['cm_' + key]
            cm[(truth, p[f])] = cm.get((truth, p[f]), 0) + 1
            if p[f] == truth:
                s[key][0] += 1
            else:
                wrong.append('%s：程式 %s／正確 %s' % (f, p[f], truth))
        t = (lab.get('人數') or '').strip()
        if t.isdigit() and p.get('人數') is not None:
            t, got = int(t), int(p['人數'])
            capped = min(got, pcs.PEOPLE_MAX) if t >= pcs.PEOPLE_MAX else got  # 標 5 = 5 人以上
            s['people'][1] += 1
            s['people'][0] += capped == t
            s['people'][2] += abs(capped - t) <= 1
            s['people'][3] += abs(capped - t)
            if capped != t:
                s['people_over' if capped > t else 'people_under'] += 1
                wrong.append('人數：程式 %d／正確 %d' % (got, t))
        if wrong:
            s['wrong'].append((len(wrong), p['檔名'], wrong))
    s['wrong'].sort(key=lambda x: (-x[0], x[1]))
    return s


def pct(a, b):
    return '%.1f%%（%d/%d）' % (100.0 * a / b, a, b) if b else '—（沒有標註）'


def confusion_md(cm):
    used = [c for c in ORDER if any(c in k for k in cm)]
    if not used:
        return '（沒有資料）\n'
    lines = ['| 正確 ＼ 程式 | ' + ' | '.join(used) + ' | 準確 |', '|---' * (len(used) + 2) + '|']
    for t in used:
        row = [cm.get((t, p), 0) for p in used]
        tot = sum(row)
        if not tot:
            continue
        cells = [('**%d**' % v if p == t else (str(v) if v else '·')) for v, p in zip(row, used)]
        lines.append('| %s | %s | %.0f%% |' % (t, ' | '.join(cells), 100.0 * cm.get((t, t), 0) / tot))
    return '\n'.join(lines) + '\n'


def top_confusions(cm, k=5):
    pairs = sorted(((v, t, p) for (t, p), v in cm.items() if t != p), reverse=True)[:k]
    return ['正確是「%s」被判成「%s」：%d 張' % (t, p, v) for v, t, p in pairs]


def report(folders, s, stage, half, name, source):
    now = datetime.datetime.now()
    out = ['# 準確率報告　%s' % now.strftime('%Y-%m-%d %H:%M'), '']
    out.append('- 程式版本：v%s　舞台顏色：%s　資料：%s%s' % (pcs.__version__, pcs.STAGE_NAMES.get(stage, stage),
                                                     '、'.join(os.path.basename(f.rstrip('\\/')) for f in folders),
                                                     '（%s 半）' % half.upper() if half else ''))
    out.append('- 結果來源：%s%s' % (source, '　備註：%s' % name if name else ''))
    out.append('- 計分照片：%d 張%s%s' % (s['n'], '；標註了但找不到照片 %d 張' % len(s['missing']) if s['missing'] else '',
                                     '；讀取失敗 %d 張' % len(s['errors_read']) if s['errors_read'] else ''))
    out += ['', '## 準確率', '', '| 項目 | 準確率 |', '|---|---|',
            '| 膚色 | %s |' % pct(*s['skin']), '| 整體 | %s |' % pct(*s['main'])]
    p = s['people']
    if p[1]:
        out.append('| 人數（完全正確） | %s |' % pct(p[0], p[1]))
        out.append('| 人數（差 1 人以內） | %s |' % pct(p[2], p[1]))
        out.append('| 人數平均差 | %.2f 人（多算 %d 張、少算 %d 張） |' % (p[3] / p[1], s['people_over'], s['people_under']))
    for title, key in (('膚色', 'cm_skin'), ('整體', 'cm_main')):
        out += ['', '## %s混淆矩陣' % title, '', '粗體是判斷正確的張數；「·」是 0。', '', confusion_md(s[key])]
        tc = top_confusions(s[key])
        if tc:
            out += ['最常見的錯誤：', ''] + ['- ' + x for x in tc] + ['']
    out += ['## 錯最多的照片（前 20 張）', '']
    if s['wrong']:
        out += ['| 檔名 | 錯在哪裡 |', '|---|---|']
        out += ['| %s | %s |' % (f, '；'.join(w)) for _, f, w in s['wrong'][:20]]
    else:
        out.append('全部正確。')
    if s['missing']:
        out += ['', '## 標註了但找不到的照片', ''] + ['- ' + m for m in s['missing'][:50]]
    return '\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description='用 labels.csv 計算準確率')
    ap.add_argument('folders', nargs='+')
    ap.add_argument('--stage', choices=list(pcs.STAGE_PRESETS), default='standard')
    ap.add_argument('--half', choices=['A', 'B', 'a', 'b'])
    ap.add_argument('--from-csv', metavar='CSV', help='不重新分析，用「匯出 CSV」的結果計分（只能搭配一個資料夾）')
    ap.add_argument('--name', default='', help='寫在報告裡的備註，例如「調整前」')
    ap.add_argument('--out', help='報告存放位置（預設 tools/eval_報告_時間.md）')
    a = ap.parse_args(argv)
    if a.from_csv and len(a.folders) != 1:
        ap.error('--from-csv 只能搭配一個資料夾')
    labels, preds = [], {}
    for f in a.folders:
        lab = [r for r in read_labels(f) if in_half(r['檔名'], a.half)]
        labels += lab
        if a.from_csv:
            preds.update(predict_from_csv(a.from_csv))
        else:
            print('分析 %s 的 %d 張標註照片…' % (f, len(lab)))
            preds.update(predict_by_analysis(f, {key_of(r['檔名']) for r in lab}, a.stage))
    s = score(labels, preds)
    text = report(a.folders, s, a.stage, a.half, a.name, '匯出的 CSV' if a.from_csv else '重新分析')
    out = a.out or os.path.join(HERE, 'eval_報告_%s.md' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    with open(out, 'w', encoding='utf-8') as fp:
        fp.write(text)
    print(text)
    print('已存報告：%s' % out)
    return s


if __name__ == '__main__':
    main()
