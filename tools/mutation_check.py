# -*- coding: utf-8 -*-
"""簡單的 mutation check：在暫存的複本裡故意把功能改壞，確認測試會失敗。
不會改到原本的程式。用法：python tools/mutation_check.py"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = 'photo_color_sorter.py'
EVAL = os.path.join('tools', 'evaluate.py')

# (說明, 檔案, 原本的程式片段, 改壞後的片段)
MUTATIONS = [
    # 階段 1：寫入 Lightroom 標籤
    ('已有星等／色標不保留，直接覆蓋', MAIN,
     "if cur and not (key == 'rating' and cur == '0'):", "if False:"),
    ('關掉「星等」功能仍寫入星等', MAIN,
     "'rating': r.get('stars') if on['stars'] else None", "'rating': r.get('stars')"),
    ('JPG／PNG／TIFF／DNG 也寫 .xmp', MAIN,
     "if os.path.splitext(f)[1].lower() in RAW_EXTS - XMP_SKIP_EXTS]", "if os.path.splitext(f)[1].lower() in RAW_EXTS | IMG_EXTS]"),
    ('復原時不檢查檔案是否被其他程式改過', MAIN,
     "if _sha(cur) != r['sha_after']:", "if False:"),
    ('寫入時不檢查路徑是否在資料夾內', MAIN,
     "                if not is_inside(path, log_dir):\n                    raise PermissionError('路徑不在所選資料夾內')\n                old = None",
     "                old = None"),
    ('屬性裡的換行沒有跳脫（重新讀取會變空白）', MAIN,
     ".replace('\\n', '&#xA;')", ""),
    ('重新寫入時不移除上次的關鍵字', MAIN,
     "    for li in ours_old:\n        hier.removeChild(li)\n", ""),
    ('復原時不刪除本工具新建的 .xmp', MAIN,
     "                os.remove(path)\n            else:\n                original", "                pass\n            else:\n                original"),
    ('寫不了紀錄檔時照樣寫入', MAIN,
     "        return done, [(p['xmp'], '無法建立紀錄檔，為了能復原所以沒有寫入：%s' % e) for p in plan], None",
     "        fp, writer = open(os.devnull, 'w'), csv.writer(open(os.devnull, 'w'))"),
    ('輸出時不固定命名空間宣告的位置（第二次執行會重寫檔案）', MAIN,
     "        attrs = [a for a in attrs if a.name.startswith('xmlns')] + [a for a in attrs if not a.name.startswith('xmlns')]\n", ""),
    ('復原紀錄指向資料夾外仍照做', MAIN,
     "    if unsafe:\n        raise PermissionError('紀錄檔中有 %d 筆路徑不在此資料夾內，為了安全已停止復原' % len(unsafe))\n    done, errors = 0, []\n    for r in reversed(rows):",
     "    done, errors = 0, []\n    for r in reversed(rows):"),
    # 人數
    ('人數沒有在 5 人合併', MAIN,
     "return '%d人以上' % PEOPLE_MAX if n >= PEOPLE_MAX else '%d人' % n", "return '%d人' % n"),
    ('人數沒有寫進關鍵字', MAIN,
     ", '%s|人數|%s' % (XMP_ROOT, people_text(r['faces']))]", "]"),
    # Lightroom 色標（依人／依背景）
    ('依人／依背景沒有作用（一律用背景）', MAIN,
     "return COLOR_TO_LABEL.get(r[label_mode])", "return COLOR_TO_LABEL.get(r['main'])"),
    ('使用者設定的色標名稱沒有用', MAIN,
     "'label': clean_label_names(label_names)[i] if i is not None else None", "'label': LR_LABELS[i] if i is not None else None"),
    ('白光也加色標', MAIN,
     "COLOR_TO_LABEL = {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 4}",
     "COLOR_TO_LABEL = {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 4, 8: 0}"),
    ('代表張沒有寫成關鍵字', MAIN,
     "        kw.append('%s|代表張' % XMP_ROOT)\n", "        pass\n"),
    # 準確率評估
    ('比對檔名時沒去掉顏色前綴', EVAL,
     "return pcs.file_stem(pcs.strip_prefix(os.path.basename(name))).lower()",
     "return pcs.file_stem(os.path.basename(name)).lower()"),
    ('「5 人以上」沒有特別處理', EVAL,
     "capped = min(got, pcs.PEOPLE_MAX) if t >= pcs.PEOPLE_MAX else got", "capped = got"),
    ('空白的標註也計分', EVAL,
     "            if not truth:\n                continue\n", ""),
]


def main():
    sources = {}
    ok_all = True
    for desc, fname, old, new in MUTATIONS:
        src = sources.setdefault(fname, open(os.path.join(ROOT, fname), encoding='utf-8').read())
        if src.count(old) != 1:
            print('[無法套用] %s：找到 %d 處' % (desc, src.count(old)))
            ok_all = False
            continue
        tmp = tempfile.mkdtemp()
        try:
            for f in os.listdir(ROOT):
                if f.endswith('.onnx') or f == MAIN:
                    shutil.copy(os.path.join(ROOT, f), tmp)
            for d in ('tests', 'tools'):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(tmp, d),
                                ignore=shutil.ignore_patterns('__pycache__', 'eval_報告_*'))
            with open(os.path.join(tmp, fname), 'w', encoding='utf-8') as fp:
                fp.write(src.replace(old, new))
            p = subprocess.run([sys.executable, '-m', 'unittest', 'discover', 'tests'],
                               cwd=tmp, capture_output=True, text=True, encoding='utf-8', errors='replace')
            caught = p.returncode != 0
            ok_all &= caught
            print('[%s] %s' % ('抓到' if caught else '沒抓到', desc))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print('全部改壞的情況都被測試抓到' if ok_all else '有改壞的情況沒被抓到，請補測試')
    sys.exit(0 if ok_all else 1)


if __name__ == '__main__':
    main()
