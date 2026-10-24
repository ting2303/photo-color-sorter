# -*- coding: utf-8 -*-
"""
舞台照片色彩分類工具 Photo Color Sorter

Required Notice: Copyright (c) 2026 ting2303 (https://github.com/ting2303/photo-color-sorter)
授權：PolyForm Noncommercial License 1.0.0（僅限非商業用途），詳見 LICENSE

功能：
  1. 偵測人臉，判斷「膚色被照成什麼顏色」（取臉部像素中佔最多數的色相）
  2. 判斷「整張照片的主要顏色」（忽略黑暗區域，以亮的有色光為主）
  3. 輸出方式二選一：
     改檔名：  DSC_1234.NEF  ->  6藍7紫_DSC_1234.NEF
               前 = 優先項目（預設膚色）、後 = 另一項，數字決定排序。
               匯入 Lightroom Classic 後用「檔案名稱」排序，就會依顏色排好。
     分資料夾：DSC_1234.NEF  ->  膚色6藍/整體7紫/DSC_1234.NEF

  - RAW + JPG + XMP 同名檔會一起改名
  - 每次執行會在資料夾內留下紀錄 CSV，可一鍵復原
  - 重複執行不會疊加前綴（會先移除舊前綴）

用法：
  圖形介面：  python photo_color_sorter.py [資料夾]
  命令列：    python photo_color_sorter.py <資料夾> --preview|--apply [--output rename|folder]
              [--mode both|skin|main] [--order skin|main] [--no-digits] [-r]
"""
import os
import re
import csv
import sys
import queue
import argparse
import hashlib
import datetime
import threading
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import cv2

__version__ = '1.0.3'

try:
    import rawpy
except ImportError:
    rawpy = None

# ---------------------------------------------------------------- 設定

RAW_EXTS = {'.cr2', '.cr3', '.crw', '.nef', '.nrw', '.arw', '.srf', '.sr2', '.raf',
            '.orf', '.rw2', '.dng', '.pef', '.srw', '.3fr', '.iiq', '.x3f', '.erf', '.kdc'}
IMG_EXTS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.webp'}
SIDECAR_EXTS = {'.xmp'}

# 色相分界（度數 0~360），對應下方 HUE_KEYS
HUE_EDGES = np.array([15, 40, 70, 160, 200, 255, 290, 345], dtype=np.float32)
HUE_KEYS = np.array([0, 1, 2, 3, 4, 5, 6, 7, 0])  # 345~360 歸回紅色

# 類別索引 -> (排序數字, 顏色字)。白 = 白光／自然膚色；無 = 沒偵測到臉（不加數字，排在最後）
CATEGORIES = [
    ('1', '紅'),
    ('2', '橙'),
    ('3', '黃'),
    ('4', '綠'),
    ('5', '青'),
    ('6', '藍'),
    ('7', '紫'),
    ('8', '粉'),
    ('0', '白'),
    ('9', '暗'),
    ('', '無'),
]
WHITE, DARK, NOFACE = 8, 9, 10

# 預覽表格的底色
TAG_COLORS = ['#ffb3b3', '#ffd6a6', '#fff3a6', '#bff0bf', '#b3f0f0', '#b3c8ff',
              '#d9b3ff', '#ffb3e6', '#f2f2f2', '#9a9a9a', '#ffffff']

DARK_V = 0.12             # 亮度低於此值視為黑暗，不列入計算
NEUTRAL_S = 0.25          # 整體：飽和度低於此值視為白光/無色
NEUTRAL_MIN_V = 0.35      # 整體：無色像素至少要這麼亮才算「白光」（避免灰暗地板干擾）
HIGHLIGHT_V = 0.92        # 整體：比這更亮……
HIGHLIGHT_S = NEUTRAL_S   # ……而且是無色 = 燈光爆點／星芒／過曝白衣
HIGHLIGHT_RAMP = (0.2, 0.5)  # 整體：爆點佔亮區低於 20% 完全不投票，20%→50% 票數逐漸恢復，50% 以上照常投票
SKIN_NATURAL_S = 0.62     # 膚色：在膚色色相範圍內且飽和度低於此值 = 自然光
SKIN_NATURAL_HUE = (5, 40)

_COLOR_CHARS = ''.join(c[1] for c in CATEGORIES)
PREFIX_RE = re.compile(r'^(?:(?:\d?[%s]){1,2}_|(?:[SM]\d{2}[^_]*_){1,2}_)' % _COLOR_CHARS)  # 新格式 | 舊版長格式
FOLDER_RE = re.compile(r'^(?:膚色|整體)\d?[%s]$' % _COLOR_CHARS)
LOG_PREFIX = '_色彩分類紀錄_'
PHOTO_EXTS = RAW_EXTS | IMG_EXTS | SIDECAR_EXTS

# ---------------------------------------------------------------- 讀圖


def _imdecode(path_or_bytes):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        buf = np.frombuffer(path_or_bytes, np.uint8)
    else:
        buf = np.fromfile(path_or_bytes, np.uint8)  # 支援中文路徑
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def load_image(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS:
        if rawpy is None:
            raise RuntimeError('需要安裝 rawpy 才能讀取 RAW：pip install rawpy')
        with rawpy.imread(path) as raw:
            try:
                thumb = raw.extract_thumb()  # 內嵌預覽圖，最快
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    img = _imdecode(thumb.data)
                else:
                    img = cv2.cvtColor(thumb.data, cv2.COLOR_RGB2BGR)
                if img is not None and max(img.shape[:2]) >= 600:
                    return img
            except Exception:
                pass
            rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    img = _imdecode(path)
    if img is None:
        raise RuntimeError('無法讀取圖片')
    return img


def resize_max(img, max_side):
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    if s >= 1:
        return img
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


def to_hsv(img):
    """回傳 h(0~360), s(0~1), v(0~1)"""
    hsv = cv2.cvtColor(img.astype(np.float32) / 255.0, cv2.COLOR_BGR2HSV)
    return hsv[..., 0], hsv[..., 1], hsv[..., 2]


def hue_category(h):
    return HUE_KEYS[np.searchsorted(HUE_EDGES, h, side='right')]

# ---------------------------------------------------------------- 整體主色


def analyze_overall(img, return_highlight=False):
    """回傳 (主色, 比例, 前三名)；return_highlight=True 時再多回傳爆點佔亮區的比例。

    燈光爆點、星芒、過曝的白衣服又亮又沒顏色，照亮度加權時票數很重，
    少數幾個爆點就能把整張照片拉成「白」，所以爆點少時不讓它們投票。
    但爆點佔亮區的比例本身就是線索：佔得越多，越可能是整片白光（過曝的白光場景），
    所以爆點的票數依比例逐漸恢復（HIGHLIGHT_RAMP），不會在某個比例突然跳成白。
    比例與前三名都是同一套加權票數的佔比。
    """
    h, s, v = to_hsv(resize_max(img, 400))
    lit = v >= DARK_V
    highlight = lit & (v > HIGHLIGHT_V) & (s < HIGHLIGHT_S)
    hl_frac = float(highlight.sum() / max(int(lit.sum()), 1))

    def done(key, ratio, top):
        return (key, ratio, top, hl_frac) if return_highlight else (key, ratio, top)

    # 用排除爆點前的亮像素判斷暗不暗；否則幾乎全過曝的照片會被誤判成「暗」
    if lit.mean() < 0.03:
        return done(DARK, 1.0, [])
    lo, hi = HIGHLIGHT_RAMP
    hl_weight = min(max((hl_frac - lo) / (hi - lo), 0.0), 1.0)  # 爆點票數的倍率 0~1
    cat = hue_category(h)
    neutral = s < NEUTRAL_S
    cat = np.where(neutral, WHITE, cat)
    # 越亮的像素權重越高；暗沉的灰色不算白光；爆點依比例打折
    w = np.where(neutral & (v < NEUTRAL_MIN_V), 0.0, v ** 2)
    w = np.where(highlight, w * hl_weight, w)
    hist = np.bincount(cat[lit], weights=w[lit], minlength=len(CATEGORIES))
    total = hist.sum()
    if total <= 0:  # 其餘都是暗沉灰色：有爆點就是白光，沒有才是暗
        return done(WHITE, 1.0, [(WHITE, 1.0)]) if highlight.any() else done(DARK, 1.0, [])
    hist = hist / total
    order = np.argsort(hist)[::-1]
    top = [(int(i), float(hist[i])) for i in order[:3] if hist[i] > 0.05]
    return done(int(order[0]), float(hist[order[0]]), top)

# ---------------------------------------------------------------- 人臉膚色


APP_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))  # 打包成 exe 時的資料位置
YUNET_MODEL = os.path.join(APP_DIR, 'face_detection_yunet_2023mar.onnx')
YUNET_SHA256 = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'
FACE_SCORE = 0.7         # YuNet 人臉信心門檻，誤判多就調高、漏抓多就調低
DETECT_SIDE = 1920        # 偵測用解析度，遠景小臉需要較高解析度

_cascades = None
_yunet = None


def _get_cascades():
    global _cascades
    if _cascades is None:
        base = cv2.data.haarcascades
        _cascades = (cv2.CascadeClassifier(os.path.join(base, 'haarcascade_frontalface_default.xml')),
                     cv2.CascadeClassifier(os.path.join(base, 'haarcascade_profileface.xml')))
    return _cascades


def _get_yunet():
    global _yunet
    if _yunet is None:
        _yunet = False
        if os.path.exists(YUNET_MODEL) and hasattr(cv2, 'FaceDetectorYN'):
            # readNet 不支援中文路徑，先讀成 bytes；並驗證模型檔沒被竄改
            data = np.fromfile(YUNET_MODEL, np.uint8)
            if hashlib.sha256(data.tobytes()).hexdigest() != YUNET_SHA256:
                raise RuntimeError('人臉模型檔驗證失敗，請重新下載本工具')
            _yunet = cv2.FaceDetectorYN.create('onnx', data, np.array([], np.uint8), (320, 320),
                                               FACE_SCORE, 0.3, 5000)
    return _yunet


def detect_faces(img):
    """偵測人臉：優先用 YuNet 深度學習模型，沒有模型時退回 Haar"""
    yunet = _get_yunet()
    if yunet:
        h, w = img.shape[:2]
        yunet.setInputSize((w, h))
        _, faces = yunet.detect(img)
        if faces is None:
            return []
        return [(int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[14]))
                for f in faces if min(f[2], f[3]) >= 10]
    frontal, profile = _get_cascades()
    gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    min_side = max(24, int(min(gray.shape) * 0.03))
    kw = dict(scaleFactor=1.1, minNeighbors=6, minSize=(min_side, min_side))
    faces = list(frontal.detectMultiScale(gray, **kw))
    if not faces:
        faces = list(profile.detectMultiScale(gray, **kw))
        flipped = profile.detectMultiScale(cv2.flip(gray, 1), **kw)
        W = gray.shape[1]
        faces += [(W - x - w, y, w, h) for (x, y, w, h) in flipped]
    return [(x, y, w, h, 1.0) for (x, y, w, h) in faces]


def analyze_skin(img):
    work = resize_max(img, DETECT_SIDE)
    faces = detect_faces(work)
    if not faces:  # 直幅照片的預覽圖可能沒轉正，試著旋轉
        for rot in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
            rotated = cv2.rotate(work, rot)
            faces = detect_faces(rotated)
            if faces:
                work = rotated
                break
    if not faces:
        return NOFACE, 0.0, 0

    # 每張臉各自投票：取臉部中央橢圓（避開頭髮與背景）統計色相，
    # 權重 = 信心分數 x 臉的大小，近景大臉影響較大、可疑的小誤判影響較小
    H, S, V = to_hsv(work)
    hist = np.zeros(len(CATEGORIES))
    for (x, y, fw, fh, score) in faces:
        mask = np.zeros(work.shape[:2], np.uint8)
        cv2.ellipse(mask, (int(x + fw / 2), int(y + fh * 0.55)), (int(fw * 0.32), int(fh * 0.36)),
                    0, 0, 360, 255, -1)
        sel = mask > 0
        h, s, v = H[sel], S[sel], V[sel]
        valid = (v >= DARK_V * 0.8) & ~((v > 0.97) & (s < 0.08))  # 去掉太暗與過曝
        if valid.sum() < 20:
            continue
        h, s = h[valid], s[valid]
        cat = hue_category(h)
        natural = (s < 0.12) | ((h >= SKIN_NATURAL_HUE[0]) & (h < SKIN_NATURAL_HUE[1]) & (s < SKIN_NATURAL_S))
        cat = np.where(natural, WHITE, cat)
        face_hist = np.bincount(cat, minlength=len(CATEGORIES)).astype(np.float64)
        hist += face_hist / face_hist.sum() * score * np.sqrt(fw * fh)
    if hist.sum() <= 0:
        return DARK, 1.0, len(faces)
    key = int(np.argmax(hist))
    return key, float(hist[key] / hist.sum()), len(faces)

# ---------------------------------------------------------------- 檔案分組與命名


def file_stem(name):
    """DSC_1.NEF / DSC_1.xmp / DSC_1.NEF.xmp 都回傳 DSC_1"""
    base, ext = os.path.splitext(name)
    if ext.lower() in SIDECAR_EXTS:
        b2, e2 = os.path.splitext(base)
        if e2.lower() in RAW_EXTS | IMG_EXTS:
            base = b2
    return base


def strip_prefix(name):
    return PREFIX_RE.sub('', name, count=1)


def is_inside(path, base):
    """path 是否位於 base 資料夾之內（含子資料夾）"""
    path, base = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(base))
    try:
        return os.path.commonpath([path, base]) == base and path != base
    except ValueError:  # 不同磁碟
        return False


def walk_photos(folder, recursive=False):
    """逐一列出 (資料夾, [檔名])；遞迴時略過本工具建立的顏色資料夾，避免重複分類"""
    if not recursive:
        yield folder, os.listdir(folder)
        return
    for d, dirs, names in os.walk(folder):
        dirs[:] = [x for x in dirs if not FOLDER_RE.match(x)]
        yield d, names


def collect_groups(folder, recursive=False):
    """回傳 [{'dir', 'stem', 'files': [...], 'source': 用來分析的檔案}]"""
    groups = {}
    for d, names in walk_photos(folder, recursive):
        for n in names:
            ext = os.path.splitext(n)[1].lower()
            if ext not in RAW_EXTS | IMG_EXTS | SIDECAR_EXTS:
                continue
            key = (d, file_stem(n))
            groups.setdefault(key, []).append(n)
    result = []
    for (d, stem), files in sorted(groups.items()):
        imgs = [f for f in files if os.path.splitext(f)[1].lower() in IMG_EXTS]
        raws = [f for f in files if os.path.splitext(f)[1].lower() in RAW_EXTS]
        if not imgs and not raws:
            continue  # 只有 xmp
        source = (imgs or raws)[0]  # 有 JPG 就用 JPG（較快）
        result.append({'dir': d, 'stem': stem, 'files': sorted(files), 'source': source})
    return result


def analyze_group(group):
    path = os.path.join(group['dir'], group['source'])
    try:
        img = load_image(path)
        skin, skin_ratio, nfaces = analyze_skin(img)
        main, main_ratio, top, highlight = analyze_overall(img, return_highlight=True)
        return dict(group, skin=skin, skin_ratio=skin_ratio, faces=nfaces,
                    main=main, main_ratio=main_ratio, top=top, highlight=highlight, error=None)
    except Exception as e:
        return dict(group, error=str(e))


def label(idx):
    return CATEGORIES[idx][1]


def tag(idx, digits=True):
    """6藍 / 藍"""
    code, name = CATEGORIES[idx]
    return (code if digits else '') + name


def slot_order(mode='both', order='skin'):
    if mode == 'skin':
        return ['skin']
    if mode == 'main':
        return ['main']
    return ['skin', 'main'] if order == 'skin' else ['main', 'skin']


def build_prefix(res, mode='both', order='skin', digits=True):
    """檔名前綴，例如 6藍7紫_（前 = 排序優先的那一項）"""
    return ''.join(tag(res[k], digits) for k in slot_order(mode, order)) + '_'


def build_subdir(res, mode='both', order='skin', digits=True):
    """分資料夾路徑，例如 膚色6藍/整體7紫"""
    names = {'skin': '膚色', 'main': '整體'}
    return os.path.join(*[names[k] + tag(res[k], digits) for k in slot_order(mode, order)])


def plan_renames(results, mode='both', order='skin', digits=True, output='rename'):
    """回傳 [(舊完整路徑, 新完整路徑)]。output='rename' 改檔名，'folder' 移到顏色子資料夾"""
    plan = []
    for r in results:
        if r.get('error'):
            continue
        for f in r['files']:
            clean = strip_prefix(f)
            if output == 'folder':
                new = os.path.join(r['dir'], build_subdir(r, mode, order, digits), clean)
            else:
                new = os.path.join(r['dir'], build_prefix(r, mode, order, digits) + clean)
            old = os.path.join(r['dir'], f)
            if new != old:
                plan.append((old, new))
    return plan


def apply_renames(plan, log_dir):
    """依計畫改名／搬移。只改名不刪檔；每完成一筆就寫入紀錄，中途中斷也能復原"""
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join(log_dir, LOG_PREFIX + '%s.csv' % stamp)
    n = 1
    while os.path.exists(log_path):
        n += 1
        log_path = os.path.join(log_dir, LOG_PREFIX + '%s_%d.csv' % (stamp, n))
    done, errors = [], []
    fp = None
    try:
        for old, new in plan:
            try:
                if not (is_inside(old, log_dir) and is_inside(new, log_dir)):
                    raise PermissionError('路徑不在所選資料夾內')
                if os.path.exists(new):
                    raise FileExistsError('目標檔名已存在')
                os.makedirs(os.path.dirname(new), exist_ok=True)
                os.rename(old, new)
            except Exception as e:
                errors.append((old, str(e)))
                continue
            done.append((old, new))
            if fp is None:
                fp = open(log_path, 'w', newline='', encoding='utf-8-sig')
                writer = csv.writer(fp)
                writer.writerow(['old', 'new'])
            writer.writerow([old, new])
            fp.flush()
    finally:
        if fp:
            fp.close()
    return done, errors, (log_path if done else None)


def latest_log(folder):
    logs = sorted(f for f in os.listdir(folder)
                  if f.startswith((LOG_PREFIX, '_色彩改名紀錄_')) and f.endswith('.csv') and '已復原' not in f)
    return os.path.join(folder, logs[-1]) if logs else None


def undo_log(log_path):
    with open(log_path, newline='', encoding='utf-8-sig') as fp:
        rows = list(csv.DictReader(fp))
    base = os.path.dirname(os.path.abspath(log_path))
    # 安全檢查：只處理紀錄檔所在資料夾內的路徑，避免被竄改的紀錄檔動到其他位置的檔案
    rows = [r for r in rows if r.get('old') and r.get('new')]
    unsafe = [r for r in rows if not (is_inside(r['old'], base) and is_inside(r['new'], base))]
    if unsafe:
        raise PermissionError('紀錄檔中有 %d 筆路徑不在此資料夾內，為了安全已停止復原' % len(unsafe))
    done, errors = 0, []
    for row in reversed(rows):
        try:
            if os.path.exists(row['new']) and not os.path.exists(row['old']):
                os.makedirs(os.path.dirname(row['old']), exist_ok=True)
                os.rename(row['new'], row['old'])
                done += 1
        except Exception as e:
            errors.append((row['new'], str(e)))
    # 移除分資料夾時建立、現在變空的顏色資料夾（只刪空資料夾）
    for d in sorted({os.path.dirname(os.path.abspath(r['new'])) for r in rows}, key=len, reverse=True):
        while is_inside(d, base) and FOLDER_RE.match(os.path.basename(d)) and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            d = os.path.dirname(d)
    os.rename(log_path, log_path[:-4] + '_已復原.csv')
    return done, errors


def strip_all_prefixes(folder, recursive=False):
    plan = []
    for d, names in walk_photos(folder, recursive):
        for n in names:
            if os.path.splitext(n)[1].lower() not in PHOTO_EXTS:
                continue  # 只動照片與 XMP，其他檔案一律不碰
            s = strip_prefix(n)
            if s != n:
                plan.append((os.path.join(d, n), os.path.join(d, s)))
    return plan


def run_analysis(groups, progress=None, workers=None):
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    results = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(analyze_group, g) for g in groups]
        for i, f in enumerate(as_completed(futs), 1):
            results.append(f.result())
            if progress:
                progress(i, len(groups))
    results.sort(key=lambda r: (r['dir'], r['stem']))
    return results

# ---------------------------------------------------------------- 圖形介面


def run_gui(initial_folder=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    try:  # 高解析度螢幕下文字清晰
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    root.title('舞台照片色彩分類工具 v%s　© 2026 ting2303・僅限非商業用途' % __version__)
    root.geometry('1150x700')

    folder = tk.StringVar()
    recursive = tk.BooleanVar(value=False)
    output = tk.StringVar(value='rename')
    mode = tk.StringVar(value='both')
    order = tk.StringVar(value='skin')
    digits = tk.BooleanVar(value=True)
    status = tk.StringVar(value='請選擇照片資料夾')
    state = {'results': [], 'busy': False}
    q = queue.Queue()

    def on_option():
        refresh_table()
        is_folder = output.get() == 'folder'
        b_apply.configure(text='② 執行分資料夾' if is_folder else '② 執行改名')
        b_strip.state(['disabled'] if is_folder or state['busy'] else ['!disabled'])

    # --- 上方控制列
    top = ttk.Frame(root, padding=8)
    top.pack(fill='x')
    ttk.Label(top, text='資料夾：').pack(side='left')
    ttk.Entry(top, textvariable=folder, width=60).pack(side='left', padx=4)
    ttk.Button(top, text='選擇…', command=lambda: folder.set(filedialog.askdirectory() or folder.get())).pack(side='left')
    ttk.Checkbutton(top, text='包含子資料夾', variable=recursive).pack(side='left', padx=8)

    opts = ttk.Frame(root, padding=(8, 0))
    opts.pack(fill='x')
    ttk.Label(opts, text='輸出方式：').pack(side='left')
    for t, v in (('改檔名', 'rename'), ('分資料夾', 'folder')):
        ttk.Radiobutton(opts, text=t, value=v, variable=output, command=on_option).pack(side='left')
    ttk.Label(opts, text='　　依據：').pack(side='left')
    for t, v in (('膚色＋整體', 'both'), ('只看膚色', 'skin'), ('只看整體', 'main')):
        ttk.Radiobutton(opts, text=t, value=v, variable=mode, command=on_option).pack(side='left')
    ttk.Label(opts, text='　　優先：').pack(side='left')
    for t, v in (('膚色', 'skin'), ('整體', 'main')):
        ttk.Radiobutton(opts, text=t, value=v, variable=order, command=on_option).pack(side='left')
    ttk.Checkbutton(opts, text='加排序數字', variable=digits, command=on_option).pack(side='left', padx=12)

    ttk.Label(root, padding=(8, 4), foreground='#555',
              text='顏色：0白(白光/自然膚色) 1紅 2橙 3黃 4綠 5青 6藍 7紫 8粉 9暗 無(沒偵測到臉)'
                   '　｜　改檔名例：6藍7紫_原檔名 → 前面是優先項目，後面是另一項').pack(fill='x')

    btns = ttk.Frame(root, padding=8)
    btns.pack(fill='x')
    b_analyze = ttk.Button(btns, text='① 分析（預覽，不動檔案）', command=lambda: start_analysis())
    b_apply = ttk.Button(btns, text='② 執行改名', command=lambda: do_apply())
    b_undo = ttk.Button(btns, text='復原上一次', command=lambda: do_undo())
    b_strip = ttk.Button(btns, text='移除所有顏色前綴', command=lambda: do_strip())
    for b in (b_analyze, b_apply, b_undo, b_strip):
        b.pack(side='left', padx=4)
    pbar = ttk.Progressbar(btns, length=250)
    pbar.pack(side='right')

    # --- 預覽表格
    cols = ('file', 'faces', 'skin', 'skin_r', 'main', 'main_r', 'top', 'hl', 'new')
    heads = ('原檔名', '臉數', '膚色', '膚色比例', '整體', '整體比例', '整體組成', '燈光爆點', '結果')
    widths = (200, 45, 50, 65, 50, 65, 170, 65, 335)
    frame = ttk.Frame(root)
    frame.pack(fill='both', expand=True, padx=8)
    tree = ttk.Treeview(frame, columns=cols, show='headings')
    for c, hd, w in zip(cols, heads, widths):
        tree.heading(c, text=hd)
        tree.column(c, width=w, anchor='w')
    sb = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side='left', fill='both', expand=True)
    sb.pack(side='right', fill='y')
    for i, c in enumerate(TAG_COLORS):
        tree.tag_configure('c%d' % i, background=c)
    tree.tag_configure('err', background='#ffdddd', foreground='#a00')

    ttk.Label(root, textvariable=status, padding=8).pack(fill='x')

    def set_busy(b):
        state['busy'] = b
        for w in (b_analyze, b_apply, b_undo, b_strip):
            w.state(['disabled'] if b else ['!disabled'])
        if not b and output.get() == 'folder':
            b_strip.state(['disabled'])

    def refresh_table():
        tree.delete(*tree.get_children())
        sort_key = slot_order(mode.get(), order.get())[0]
        for r in state['results']:
            if r.get('error'):
                tree.insert('', 'end', values=(r['source'], '', '錯誤', '', '', '', r['error'], '', ''), tags=('err',))
                continue
            clean = strip_prefix(r['source'])
            if output.get() == 'folder':
                new = os.path.join(build_subdir(r, mode.get(), order.get(), digits.get()), clean)
            else:
                new = build_prefix(r, mode.get(), order.get(), digits.get()) + clean
            extra = len(r['files']) - 1
            if extra:
                new += '  (+%d 個同名檔)' % extra
            top3 = ' '.join('%s%d%%' % (label(i), p * 100) for i, p in r['top'])
            tree.insert('', 'end', tags=('c%d' % r[sort_key],), values=(
                r['source'], r['faces'], label(r['skin']),
                '%d%%' % (r['skin_ratio'] * 100) if r['skin'] != NOFACE else '',
                label(r['main']), '%d%%' % (r['main_ratio'] * 100), top3,
                '%d%%' % (r.get('highlight', 0) * 100), new))

    def check_folder():
        f = folder.get().strip()
        if not f or not os.path.isdir(f):
            messagebox.showwarning('提示', '請先選擇有效的資料夾')
            return None
        return f

    def start_analysis():
        f = check_folder()
        if not f:
            return
        groups = collect_groups(f, recursive.get())
        if not groups:
            messagebox.showinfo('提示', '資料夾中沒有支援的照片')
            return
        set_busy(True)
        pbar['maximum'] = len(groups)
        pbar['value'] = 0
        status.set('分析中… 共 %d 張' % len(groups))

        def worker():
            try:
                res = run_analysis(groups, progress=lambda i, n: q.put(('progress', i, n)))
                q.put(('done', res))
            except Exception as e:
                q.put(('fail', str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            while True:
                msg = q.get_nowait()
                if msg[0] == 'progress':
                    pbar['value'] = msg[1]
                    status.set('分析中… %d / %d' % (msg[1], msg[2]))
                elif msg[0] == 'done':
                    state['results'] = msg[1]
                    refresh_table()
                    errs = sum(1 for r in msg[1] if r.get('error'))
                    status.set('分析完成：%d 張%s。可切換上方選項看結果，確認後按「②」。'
                               % (len(msg[1]), '，%d 張讀取失敗' % errs if errs else ''))
                    set_busy(False)
                elif msg[0] == 'fail':
                    set_busy(False)
                    messagebox.showerror('錯誤', msg[1])
        except queue.Empty:
            pass
        root.after(100, poll)

    def do_apply():
        f = check_folder()
        if not f:
            return
        if not state['results']:
            messagebox.showinfo('提示', '請先按「① 分析」')
            return
        is_folder = output.get() == 'folder'
        plan = plan_renames(state['results'], mode.get(), order.get(), digits.get(), output.get())
        if not plan:
            messagebox.showinfo('提示', '沒有需要處理的檔案')
            return
        action = '移到顏色資料夾' if is_folder else '改名'
        if not messagebox.askyesno('確認', '即將把 %d 個檔案%s。\n\n提醒：若照片「已經匯入」Lightroom，'
                                   '在外部改名或搬移會讓 LR 找不到檔案，建議在匯入前執行。\n\n要繼續嗎？'
                                   % (len(plan), action)):
            return
        done, errors, log = apply_renames(plan, f)
        state['results'] = []
        refresh_table()
        msg = '已%s %d 個檔案。' % (action, len(done))
        if log:
            msg += '\n紀錄檔：%s' % os.path.basename(log)
        if errors:
            msg += '\n\n%d 個失敗：\n' % len(errors) + '\n'.join('%s：%s' % (os.path.basename(a), b) for a, b in errors[:10])
        status.set(msg.split('\n')[0])
        messagebox.showinfo('完成', msg)

    def do_undo():
        f = check_folder()
        if not f:
            return
        log = latest_log(f)
        if not log:
            messagebox.showinfo('提示', '這個資料夾沒有可復原的紀錄')
            return
        if not messagebox.askyesno('確認', '要依照 %s 把檔案還原嗎？' % os.path.basename(log)):
            return
        try:
            n, errors = undo_log(log)
        except Exception as e:
            messagebox.showerror('無法復原', str(e))
            return
        state['results'] = []
        refresh_table()
        status.set('已復原 %d 個檔案' % n)
        messagebox.showinfo('完成', '已復原 %d 個檔案' % n + ('\n%d 個失敗' % len(errors) if errors else ''))

    def do_strip():
        f = check_folder()
        if not f:
            return
        plan = strip_all_prefixes(f, recursive.get())
        if not plan:
            messagebox.showinfo('提示', '沒有找到帶顏色前綴的檔案')
            return
        if not messagebox.askyesno('確認', '要移除 %d 個檔案的顏色前綴嗎？' % len(plan)):
            return
        done, errors, _ = apply_renames(plan, f)
        status.set('已移除 %d 個檔案的前綴' % len(done))
        messagebox.showinfo('完成', '已移除 %d 個檔案的前綴' % len(done) + ('\n%d 個失敗' % len(errors) if errors else ''))

    poll()
    if initial_folder:
        folder.set(os.path.abspath(initial_folder))
        root.after(300, start_analysis)
    root.mainloop()

# ---------------------------------------------------------------- 命令列


def run_cli(argv):
    ap = argparse.ArgumentParser(description='舞台照片色彩分類')
    ap.add_argument('folder')
    ap.add_argument('--preview', action='store_true', help='只預覽（預設行為）')
    ap.add_argument('--apply', action='store_true', help='實際執行（不加只預覽）')
    ap.add_argument('--output', choices=['rename', 'folder'], default='rename', help='改檔名或分資料夾')
    ap.add_argument('--mode', choices=['both', 'skin', 'main'], default='both')
    ap.add_argument('--order', choices=['skin', 'main'], default='skin')
    ap.add_argument('--no-digits', action='store_true', help='不加排序數字')
    ap.add_argument('-r', '--recursive', action='store_true')
    a = ap.parse_args(argv)

    groups = collect_groups(a.folder, a.recursive)
    print('共 %d 張，分析中…' % len(groups))
    results = run_analysis(groups, progress=lambda i, n: print('\r%d/%d' % (i, n), end='', flush=True))
    print()
    for r in results:
        if r.get('error'):
            print('[錯誤] %s：%s' % (r['source'], r['error']))
        else:
            print('%-40s 臉:%d 膚色:%s(%d%%) 整體:%s(%d%%) 爆點:%d%%' % (
                r['source'], r['faces'], label(r['skin']), r['skin_ratio'] * 100,
                label(r['main']), r['main_ratio'] * 100, r.get('highlight', 0) * 100))
    plan = plan_renames(results, a.mode, a.order, not a.no_digits, a.output)
    for old, new in plan:
        print('  %s -> %s' % (os.path.basename(old), os.path.relpath(new, os.path.dirname(old))))
    if a.apply:
        done, errors, log = apply_renames(plan, a.folder)
        print('已處理 %d 個，失敗 %d 個，紀錄：%s' % (len(done), len(errors), log))
    else:
        print('（預覽模式，加上 --apply 才會執行）')


if __name__ == '__main__':
    multiprocessing.freeze_support()  # 打包成 exe 時多核心分析需要
    if sys.stdout is None:  # 無主控台的 exe
        sys.stdout = sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    args = sys.argv[1:]
    if any(a.startswith('--') for a in args):
        run_cli(args)
    else:
        # 沒有參數 = 開視窗；把資料夾拖到程式圖示上 = 開視窗並自動分析該資料夾
        run_gui(args[0] if args and os.path.isdir(args[0]) else None)
