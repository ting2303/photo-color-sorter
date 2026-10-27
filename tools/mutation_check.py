# -*- coding: utf-8 -*-
"""簡單的 mutation check：在暫存的複本裡故意把功能改壞，確認對應的測試會失敗。
不會改到原本的程式。用法：python tools/mutation_check.py [測試類別名稱]"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (說明, 原本的程式片段, 改壞後的片段)
MUTATIONS = [
    ('已有星等／色標不保留，直接覆蓋',
     "if cur and not (key == 'rating' and cur == '0'):", "if False:"),
    ('關掉「星等」功能仍寫入星等',
     "'rating': r.get('stars') if on['stars'] else None", "'rating': r.get('stars')"),
    ('JPG／PNG／TIFF／DNG 也寫 .xmp',
     "if os.path.splitext(f)[1].lower() in RAW_EXTS - XMP_SKIP_EXTS]", "if os.path.splitext(f)[1].lower() in RAW_EXTS | IMG_EXTS]"),
    ('復原時不檢查檔案是否被其他程式改過',
     "if _sha(cur) != r['sha_after']:", "if False:"),
    ('寫入時不檢查路徑是否在資料夾內',
     "                if not is_inside(path, log_dir):\n                    raise PermissionError('路徑不在所選資料夾內')\n                old = None",
     "                old = None"),
    ('屬性裡的換行沒有跳脫（重新讀取會變空白）',
     ".replace('\\n', '&#xA;')", ""),
    ('重新寫入時不移除上次的關鍵字',
     "    for li in ours_old:\n        hier.removeChild(li)\n", ""),
    ('復原時不刪除本工具新建的 .xmp',
     "                os.remove(path)\n            else:\n                original", "                pass\n            else:\n                original"),
    ('寫不了紀錄檔時照樣寫入',
     "        return done, [(p['xmp'], '無法建立紀錄檔，為了能復原所以沒有寫入：%s' % e) for p in plan], None",
     "        fp, writer = open(os.devnull, 'w'), csv.writer(open(os.devnull, 'w'))"),
    ('輸出時不固定命名空間宣告的位置（第二次執行會重寫檔案）',
     "        attrs = [a for a in attrs if a.name.startswith('xmlns')] + [a for a in attrs if not a.name.startswith('xmlns')]\n", ""),
    ('復原紀錄指向資料夾外仍照做',
     "    if unsafe:\n        raise PermissionError('紀錄檔中有 %d 筆路徑不在此資料夾內，為了安全已停止復原' % len(unsafe))\n    done, errors = 0, []\n    for r in reversed(rows):",
     "    done, errors = 0, []\n    for r in reversed(rows):"),
]


def main():
    test_class = sys.argv[1] if len(sys.argv) > 1 else 'XmpTests'
    src = open(os.path.join(ROOT, 'photo_color_sorter.py'), encoding='utf-8').read()
    ok_all = True
    for desc, old, new in MUTATIONS:
        if src.count(old) != 1:
            print('[無法套用] %s：找到 %d 處' % (desc, src.count(old)))
            ok_all = False
            continue
        tmp = tempfile.mkdtemp()
        try:
            for f in os.listdir(ROOT):
                if f.endswith('.onnx'):
                    shutil.copy(os.path.join(ROOT, f), tmp)
            shutil.copytree(os.path.join(ROOT, 'tests'), os.path.join(tmp, 'tests'))
            with open(os.path.join(tmp, 'photo_color_sorter.py'), 'w', encoding='utf-8') as fp:
                fp.write(src.replace(old, new))
            p = subprocess.run([sys.executable, '-m', 'unittest', '-k', test_class, 'discover', 'tests'],
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
