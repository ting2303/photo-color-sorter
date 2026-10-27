# -*- coding: utf-8 -*-
"""標註小工具：一張張看照片，用鍵盤標「膚色、整體、人數」，存成資料夾裡的 labels.csv，給 tools/evaluate.py 計算準確率。

用法：python tools/label_tool.py [照片資料夾] [--sample 150] [--all]
  預設從資料夾隨機抽 150 張（固定亂數，重開會是同一批）；--all 標全部。
  已經標過的照片會跳過，可以分好幾次標。

按鍵（數字和檔名前綴一樣）：
  1紅 2橙 3黃 4綠 5青 6藍 7紫 8粉 0白 9暗   N = 無（沒有臉，只用在膚色）
  順序：先按膚色 → 再按整體 → 再按人數（0~9，5 以上按 5；Enter 跳過人數）
  S = 這張不確定，整張跳過（不計分）　←／Backspace = 回上一張重標　Esc = 存檔離開
  不會顯示程式判斷的結果，避免影響你的判斷。
"""
import argparse
import base64
import csv
import os
import random
import sys
import threading

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import photo_color_sorter as pcs  # noqa: E402

LABELS_NAME = 'labels.csv'
FIELDS = ['檔名', '膚色', '整體', '人數', '備註']
KEY_COLORS = {c[0]: c[1] for c in pcs.CATEGORIES if c[0]}  # '6' -> '藍'


def read_labels(path):
    if not os.path.exists(path):
        return {}
    with open(path, newline='', encoding='utf-8-sig') as fp:
        reader = csv.DictReader(fp)
        if '檔名' not in (reader.fieldnames or []):
            raise ValueError('%s 不是標註檔（第一列沒有「檔名」），為了不蓋掉它，請改名或移走' % path)
        return {r['檔名']: r for r in reader if r.get('檔名')}


def write_labels(path, labels):
    tmp = path + '.tmp'
    with open(tmp, 'w', newline='', encoding='utf-8-sig') as fp:
        w = csv.DictWriter(fp, fieldnames=FIELDS, extrasaction='ignore')
        w.writeheader()
        for name in sorted(labels):
            w.writerow(labels[name])
    os.replace(tmp, path)


def pick_photos(folder, sample, use_all, seed=1017):
    groups = pcs.collect_groups(folder)
    names = sorted(g['source'] for g in groups)
    paths = {g['source']: os.path.join(g['dir'], g['source']) for g in groups}
    if not use_all and len(names) > sample:
        names = sorted(random.Random(seed).sample(names, sample))
    return names, paths


def run(folder, sample, use_all):
    import tkinter as tk
    from tkinter import messagebox, filedialog
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    root.title('標註小工具')
    root.geometry('1200x860')
    if not folder:
        folder = filedialog.askdirectory(title='選擇要標註的照片資料夾')
        if not folder:
            return
    out = os.path.join(folder, LABELS_NAME)
    try:
        labels = read_labels(out)
    except ValueError as e:
        messagebox.showerror('無法開始', str(e))
        return
    names, paths = pick_photos(folder, sample, use_all)
    todo = [n for n in names if n not in labels]
    st = {'i': 0, 'step': 0, 'cur': {}, 'img': None, 'cache': {}, 'history': []}

    info = tk.Label(root, font=('Microsoft JhengHei UI', 12), anchor='w', justify='left')
    info.pack(fill='x', padx=10, pady=(8, 0))
    prompt = tk.Label(root, font=('Microsoft JhengHei UI', 16, 'bold'), anchor='w', fg='#1f4fbf')
    prompt.pack(fill='x', padx=10)
    keys = tk.Label(root, font=('Microsoft JhengHei UI', 11), anchor='w', fg='#555',
                    text='1紅 2橙 3黃 4綠 5青 6藍 7紫 8粉 0白 9暗 N無　｜　S 跳過　←／Backspace 上一張　Esc 存檔離開')
    keys.pack(fill='x', padx=10)
    canvas = tk.Label(root, bg='#222')
    canvas.pack(fill='both', expand=True, padx=10, pady=10)

    def load(name):
        """讀圖並縮成視窗大小的 PNG（在背景執行緒先讀下一張）"""
        if name in st['cache']:
            return st['cache'][name]
        try:
            img = pcs.load_image(paths[name])
            img = pcs.resize_max(img, 1400)
            h, w = img.shape[:2]
            s = min(1150 / w, 700 / h, 1.0)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.png', img)
            data = base64.b64encode(buf.tobytes()).decode()
        except Exception as e:
            data = 'ERR:%s' % e
        st['cache'][name] = data
        return data

    def preload(k):
        if 0 <= k < len(todo):
            threading.Thread(target=load, args=(todo[k],), daemon=True).start()

    def show():
        done = len([n for n in names if n in labels])
        if st['i'] >= len(todo):
            write_labels(out, labels)
            prompt.config(text='全部標完了！共 %d 張，已存到 %s' % (len(labels), out))
            canvas.config(image='', text='可以關掉視窗了', fg='white', font=('Microsoft JhengHei UI', 20))
            return
        name = todo[st['i']]
        info.config(text='%s　（這一批 %d / %d，已標 %d 張）' % (name, done + 1, len(names), done))
        steps = ['① 膚色：臉被照成什麼顏色？（沒有臉按 N）', '② 整體：整張照片的主色？', '③ 人數：看得到臉的有幾個人？（0~9，5 以上按 5；Enter 跳過）']
        cur = st['cur']
        got = '　已選：' + '／'.join(x for x in (cur.get('膚色'), cur.get('整體')) if x) if cur else ''
        prompt.config(text=steps[st['step']] + got)
        data = load(name)
        if data.startswith('ERR:'):
            canvas.config(image='', text='無法預覽：%s\n按 S 跳過' % data[4:], fg='white')
        else:
            st['img'] = tk.PhotoImage(data=data)
            canvas.config(image=st['img'], text='')
        preload(st['i'] + 1)

    def finish(row):
        labels[todo[st['i']]] = row
        write_labels(out, labels)  # 每張都存，隨時關掉也不會不見
        st['history'].append(st['i'])
        st['i'] += 1
        st['step'], st['cur'] = 0, {}
        show()

    def on_key(e):
        if st['i'] >= len(todo):
            return
        k = e.keysym.lower()
        ch = e.char or (k[-1] if k.startswith('kp_') or len(k) == 1 else '')  # 數字鍵盤（kp_6）也可以用
        name = todo[st['i']]
        if k == 'escape':
            write_labels(out, labels)
            root.destroy()
            return
        if k in ('backspace', 'left'):
            if st['step'] > 0:
                st['step'], st['cur'] = 0, {}
            elif st['history']:
                st['i'] = st['history'].pop()
                labels.pop(todo[st['i']], None)
                write_labels(out, labels)
            show()
            return
        if k == 's':
            finish({'檔名': name, '膚色': '', '整體': '', '人數': '', '備註': '不確定，跳過'})
            return
        if st['step'] == 0:
            if k == 'n':
                st['cur']['膚色'] = '無'
            elif ch in KEY_COLORS:
                st['cur']['膚色'] = KEY_COLORS[ch]
            else:
                return
            st['step'] = 1
        elif st['step'] == 1:
            if ch not in KEY_COLORS:
                return
            st['cur']['整體'] = KEY_COLORS[ch]
            st['step'] = 2
        else:
            if k == 'return':
                n = ''
            elif ch.isdigit():
                n = ch
            else:
                return
            finish({'檔名': name, '膚色': st['cur']['膚色'], '整體': st['cur']['整體'], '人數': n, '備註': ''})
            return
        show()

    root.bind('<Key>', on_key)
    root.protocol('WM_DELETE_WINDOW', lambda: (write_labels(out, labels), root.destroy()))
    if not todo:
        messagebox.showinfo('已經標完', '這一批 %d 張都標過了（%s）。\n要標更多，請加上 --sample 更大的數字或 --all。' % (len(names), out))
        root.destroy()
        return
    show()
    root.after(200, root.focus_force)  # 一打開就能直接按鍵，不用先點視窗
    root.mainloop()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='標註照片的正確顏色，給 evaluate.py 計算準確率')
    ap.add_argument('folder', nargs='?')
    ap.add_argument('--sample', type=int, default=150, help='隨機抽幾張（預設 150）')
    ap.add_argument('--all', action='store_true', help='標全部照片')
    a = ap.parse_args()
    run(a.folder, a.sample, a.all)
