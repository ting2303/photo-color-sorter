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
  4. 挑圖輔助（只顯示在表格與匯出的 CSV，不改變檔名格式）：
     拍攝時間（EXIF）、燈光段落、清晰度、每段代表張、主色不確定標示「?」、
     「整體偏重演出者」選項（背景 LED 螢幕很花時使用）

用法：
  圖形介面：  python photo_color_sorter.py [資料夾]
  命令列：    python photo_color_sorter.py <資料夾> --preview|--apply [--output rename|folder]
              [--mode both|skin|main] [--order skin|main] [--no-digits] [-r]
              [--performer] [--csv 結果.csv]
"""
import os
import re
import csv
import sys
import queue
import argparse
import struct
import hashlib
import datetime
import threading
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import cv2

__version__ = '1.1.0'

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
PERFORMER_WEIGHT = 3.0    # 「整體偏重演出者」：演出者周圍的票數倍率
UNCERTAIN_RATIO = 0.35    # 主色票數低於此比例時，表格標示「?」（不影響檔名）
SCENE_GAP_SEC = 60        # 燈光段落：兩張照片間隔超過這麼多秒就切成新段落
SCENE_MIN_LEN = 3         # 燈光段落：少於這麼多張的段落併入前一段（避免單張誤判切出一堆小段）
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
    return cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)


def to_hsv(img):
    """回傳 h(0~360), s(0~1), v(0~1)"""
    hsv = cv2.cvtColor(img.astype(np.float32) / 255.0, cv2.COLOR_BGR2HSV)
    return hsv[..., 0], hsv[..., 1], hsv[..., 2]


def hue_category(h):
    return HUE_KEYS[np.searchsorted(HUE_EDGES, h, side='right')]

# ---------------------------------------------------------------- 整體主色


def performer_weight_map(shape, boxes):
    """演出者區域的權重圖：臉框往左右各擴 1.6 個臉寬、往上 0.5 個臉高、往下 8 個臉高（約到膝蓋）。
    boxes 是相對座標 (x, y, w, h)，0~1。區域內權重 PERFORMER_WEIGHT，區域外 1。"""
    H, W = shape[:2]
    wmap = np.ones((H, W), np.float32)
    for (x, y, w, h) in boxes:
        x0, x1 = int((x - 1.6 * w) * W), int((x + 2.6 * w) * W)
        y0, y1 = int((y - 0.5 * h) * H), int((y + 9 * h) * H)
        wmap[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)] = PERFORMER_WEIGHT
    return wmap


def analyze_overall(img, return_highlight=False, performer_boxes=None):
    """回傳 (主色, 比例, 前三名)；return_highlight=True 時再多回傳爆點佔亮區的比例。
    performer_boxes：演出者臉框（相對座標 0~1）；有給時，演出者周圍的票數乘上 PERFORMER_WEIGHT，
    減少背景 LED 螢幕搶走主色的情況。

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
    if performer_boxes:
        w = w * performer_weight_map(h.shape, performer_boxes)
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


def analyze_skin(img, return_faces=False):
    """回傳 (膚色, 比例, 臉數)；return_faces=True 時再多回傳 (臉框清單, 偵測用的圖)。
    臉框是偵測用圖上的 (x, y, w, h, 信心)；照片被轉正過時，偵測用圖與原圖方向不同。"""
    work = resize_max(img, DETECT_SIDE)
    faces = detect_faces(work)
    rotated_work = False
    if not faces:  # 直幅照片的預覽圖可能沒轉正，試著旋轉
        for rot in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
            rotated = cv2.rotate(work, rot)
            faces = detect_faces(rotated)
            if faces:
                work = rotated
                rotated_work = True
                break

    def done(key, ratio, n):
        return (key, ratio, n, faces, work, rotated_work) if return_faces else (key, ratio, n)

    if not faces:
        return done(NOFACE, 0.0, 0)

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
        return done(DARK, 1.0, len(faces))
    key = int(np.argmax(hist))
    return done(key, float(hist[key] / hist.sum()), len(faces))

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
    """逐一列出 (資料夾, [檔名])；遞迴時略過本工具建立的顏色資料夾，避免重複分類。
    以「.」開頭的隱藏檔（含 macOS 的 ._ 附屬檔）與隱藏資料夾一律略過。"""
    if not recursive:
        yield folder, [n for n in os.listdir(folder) if not n.startswith('.')]
        return
    for d, dirs, names in os.walk(folder):
        dirs[:] = [x for x in dirs if not FOLDER_RE.match(x) and not x.startswith('.')]
        yield d, [n for n in names if not n.startswith('.')]


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


# ---------------------------------------------------------------- 挑圖輔助


def _tiff_capture_time(fp, base):
    """從 TIFF 結構（JPG 的 EXIF 區塊、或 NEF/ARW/CR2/DNG 等 RAW）讀出拍攝時間字串與小數秒"""
    fp.seek(base)
    hdr = fp.read(8)
    if len(hdr) < 8 or hdr[:2] not in (b'II', b'MM'):
        return None, ''
    e = '<' if hdr[:2] == b'II' else '>'
    if struct.unpack(e + 'H', hdr[2:4])[0] not in (42, 0x55, 0x4F52):  # TIFF / Panasonic RW2 / Olympus ORF
        return None, ''

    def read_ifd(off):
        fp.seek(base + off)
        raw = fp.read(2)
        if len(raw) < 2:
            return {}
        n = struct.unpack(e + 'H', raw)[0]
        if n > 1000:
            return {}
        out = {}
        for _ in range(n):
            ent = fp.read(12)
            if len(ent) < 12:
                break
            tag_id, typ, cnt = struct.unpack(e + 'HHI', ent[:8])
            out[tag_id] = (typ, cnt, ent[8:12])
        return out

    def ascii_of(entry):
        typ, cnt, val = entry
        if typ != 2 or cnt > 64:
            return ''
        if cnt <= 4:
            data = val[:cnt]
        else:
            fp.seek(base + struct.unpack(e + 'I', val)[0])
            data = fp.read(cnt)
        return data.split(b'\0')[0].decode('ascii', 'ignore').strip()

    ifd0 = read_ifd(struct.unpack(e + 'I', hdr[4:8])[0])
    dt, sub = '', ''
    if 0x8769 in ifd0:  # EXIF 子目錄
        exif = read_ifd(struct.unpack(e + 'I', ifd0[0x8769][2])[0])
        if 0x9003 in exif:
            dt = ascii_of(exif[0x9003])  # DateTimeOriginal
        if 0x9291 in exif:
            sub = ascii_of(exif[0x9291])  # SubSecTimeOriginal（連拍時分辨先後）
    if not dt and 0x0132 in ifd0:
        dt = ascii_of(ifd0[0x0132])  # DateTime
    return dt or None, sub


def read_capture_time(path):
    """回傳拍攝時間（datetime），讀不到時回傳 None。只讀檔頭，不解碼整張照片。"""
    try:
        with open(path, 'rb') as fp:
            head = fp.read(2)
            if head == b'\xff\xd8':  # JPEG：找 APP1 Exif 區塊
                while True:
                    m = fp.read(4)
                    if len(m) < 4 or m[0] != 0xFF or m[1] in (0xDA, 0xD9):
                        return None
                    seg_len = struct.unpack('>H', m[2:4])[0]
                    start = fp.tell()
                    if m[1] == 0xE1 and fp.read(6) == b'Exif\0\0':
                        dt, sub = _tiff_capture_time(fp, start + 6)
                        break
                    fp.seek(start + seg_len - 2)
            else:
                dt, sub = _tiff_capture_time(fp, 0)
        if not dt:
            return None
        t = datetime.datetime.strptime(dt[:19], '%Y:%m:%d %H:%M:%S')
        digits = ''.join(c for c in sub if c.isdigit())[:6]
        if digits:
            t += datetime.timedelta(microseconds=int(digits.ljust(6, '0')))
        return t
    except Exception:
        return None


def group_capture_time(group):
    """(時間, 來源)：先找同名檔中任何一個的 EXIF，都沒有才用檔案修改時間"""
    for f in [group['source']] + [x for x in group['files'] if x != group['source']]:
        if os.path.splitext(f)[1].lower() in SIDECAR_EXTS:
            continue
        t = read_capture_time(os.path.join(group['dir'], f))
        if t:
            return t, 'EXIF'
    mtime = os.path.getmtime(os.path.join(group['dir'], group['source']))
    return datetime.datetime.fromtimestamp(mtime), '檔案時間'


def _grad_energy(c, sigma):
    b = cv2.GaussianBlur(c, (0, 0), sigma)
    gx = cv2.Sobel(b, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(b, cv2.CV_32F, 0, 1)
    return float(np.mean(gx * gx + gy * gy)) * sigma * sigma


def photo_metrics(work, faces):
    """清晰度、最大臉的邊長（像素）、臉部亮度（0~1）。
    清晰度 = 細尺度與粗尺度邊緣能量的比值：對焦清楚時細節多、比值高；
    不受整體亮暗與對比影響，比拉普拉斯變異數更不容易被暗場雜訊騙。"""
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY).astype(np.float32)
    H, W = gray.shape
    if faces:
        x, y, w, h, _ = max(faces, key=lambda f: f[2] * f[3])
        crop = gray[max(y, 0):max(y + h, 1), max(x, 0):max(x + w, 1)]
        mask = np.zeros(gray.shape, np.uint8)
        cv2.ellipse(mask, (int(x + w / 2), int(y + h * 0.55)), (int(w * 0.32), int(h * 0.36)), 0, 0, 360, 255, -1)
        face_px = float(np.sqrt(w * h))
        face_bright = float(np.median(gray[mask > 0]) / 255) if (mask > 0).any() else None
    else:
        crop = gray[H // 4:3 * H // 4, W // 4:3 * W // 4]
        face_px, face_bright = 0.0, None
    if crop.size < 16:
        return 0.0, face_px, face_bright
    c = cv2.resize(crop, (160, 160), interpolation=cv2.INTER_AREA)
    c = c / (c.std() + 1e-3)
    sharp = _grad_energy(c, 2) / max(_grad_energy(c, 5), 1e-9)
    return float(sharp), face_px, face_bright


def analyze_group(group):
    path = os.path.join(group['dir'], group['source'])
    try:
        img = load_image(path)
        skin, skin_ratio, nfaces, faces, work, rotated = analyze_skin(img, return_faces=True)
        main, main_ratio, top, highlight = analyze_overall(img, return_highlight=True)
        # 「整體偏重演出者」的結果也先算好，切換選項時不必重新分析
        boxes = []
        if faces and not rotated:
            Hw, Ww = work.shape[:2]
            boxes = [(x / Ww, y / Hw, w / Ww, h / Hw) for (x, y, w, h, _) in faces]
        if boxes:
            main_p, main_p_ratio, top_p = analyze_overall(img, performer_boxes=boxes)
        else:
            main_p, main_p_ratio, top_p = main, main_ratio, top
        sharp, face_px, face_bright = photo_metrics(work, faces)
        t, t_src = group_capture_time(group)
        return dict(group, skin=skin, skin_ratio=skin_ratio, faces=nfaces,
                    main=main, main_ratio=main_ratio, top=top, highlight=highlight,
                    main_perf=main_p, main_perf_ratio=main_p_ratio, top_perf=top_p,
                    sharp=sharp, face_px=face_px, face_bright=face_bright,
                    time=t, time_src=t_src, error=None)
    except Exception as e:
        return dict(group, error=str(e))


def effective(r, performer=False):
    """依「整體偏重演出者」選項，回傳要拿來命名的結果"""
    if performer and not r.get('error') and 'main_perf' in r:
        return dict(r, main=r['main_perf'], main_ratio=r['main_perf_ratio'], top=r['top_perf'])
    return r


def _smooth(labels, gaps_ok, half=3):
    """前後各 half 張的多數決平滑，不跨越長時間停頓；避免單張誤判把段落切碎"""
    out = list(labels)
    n = len(labels)
    for i in range(n):
        lo = hi = i
        while lo > 0 and i - lo < half and gaps_ok[lo]:
            lo -= 1
        while hi < n - 1 and hi - i < half and gaps_ok[hi + 1]:
            hi += 1
        win = labels[lo:hi + 1]
        best = max(win.count(x) for x in win)
        if win.count(labels[i]) < best:
            out[i] = max(win, key=win.count)
    return out


def batch_features(results, mode='both', order='skin', performer=False):
    """整批照片的挑圖資訊：依拍攝時間排序、切燈光段落、清晰度分數（0~100，整批相對）、每段代表張。
    回傳新的結果清單（照時間排序），每筆多了 scene、rep、sharp_score、uncertain。"""
    rows = [effective(r, performer) for r in results]
    ok = [r for r in rows if not r.get('error')]
    bad = [r for r in rows if r.get('error')]
    if not ok:
        return rows
    ok.sort(key=lambda r: (r['time'], r['dir'], r['stem']))
    sharps = np.array([r['sharp'] for r in ok])
    ranks = sharps.argsort().argsort()
    gaps_ok = [False] + [(ok[i]['time'] - ok[i - 1]['time']).total_seconds() <= SCENE_GAP_SEC
                         for i in range(1, len(ok))]
    # 段落 = 燈光換了：依整體主色切（膚色常被判成自然光，不適合用來切），先平滑掉單張誤判
    colors = _smooth([r['main'] for r in ok], gaps_ok)
    runs = []  # [起點, 長度]
    for i in range(len(ok)):
        if i and gaps_ok[i] and colors[i] == colors[i - 1]:
            runs[-1][1] += 1
        else:
            runs.append([i, 1])
    # 太短的段落（少於 SCENE_MIN_LEN 張，且與前一段之間沒有長時間停頓）併入前一段
    merged = []
    for start, n in runs:
        if merged and n < SCENE_MIN_LEN and gaps_ok[start]:
            merged[-1][1] += n
        else:
            merged.append([start, n])
    seg = []
    for k, (start, n) in enumerate(merged):
        seg += [k] * n
    out = []
    for i, r in enumerate(ok):
        out.append(dict(r, scene=seg[i] + 1,
                        sharp_score=int(round(100 * ranks[i] / max(len(ok) - 1, 1))) if len(ok) > 1 else 100,
                        uncertain=r['main_ratio'] < UNCERTAIN_RATIO, rep=False))
    # 每段代表張：清晰度 50% + 臉的大小 25% + 臉部亮度接近中間 25%；有臉的照片優先
    by_scene = {}
    for r in out:
        by_scene.setdefault(r['scene'], []).append(r)
    for members in by_scene.values():
        with_face = [r for r in members if r['faces']] or members
        big = max(r['face_px'] for r in with_face) or 1.0

        def score(r):
            expo = 1 - min(abs(r['face_bright'] - 0.55) / 0.55, 1) if r['face_bright'] is not None else 0.5
            return 0.5 * r['sharp_score'] / 100 + 0.25 * r['face_px'] / big + 0.25 * expo
        max(with_face, key=score)['rep'] = True
    return out + bad


def export_csv(rows, path, mode='both', order='skin', digits=True, output='rename'):
    """把分析結果（含挑圖資訊）存成 CSV，可用 Excel 開啟"""
    with open(path, 'w', newline='', encoding='utf-8-sig') as fp:
        wr = csv.writer(fp)
        wr.writerow(['檔名', '拍攝時間', '時間來源', '燈光段落', '代表張', '清晰度', '臉數', '膚色', '膚色比例',
                     '整體', '整體比例', '整體組成', '燈光爆點', '不確定', '結果', '錯誤'])
        for r in rows:
            if r.get('error'):
                wr.writerow([r['source']] + [''] * 14 + [r['error']])
                continue
            clean = strip_prefix(r['source'])
            new = (os.path.join(build_subdir(r, mode, order, digits), clean) if output == 'folder'
                   else build_prefix(r, mode, order, digits) + clean)
            wr.writerow([r['source'], r['time'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], r['time_src'],
                         'S%02d' % r['scene'], '★' if r['rep'] else '', r['sharp_score'], r['faces'],
                         label(r['skin']), '%d%%' % (r['skin_ratio'] * 100) if r['skin'] != NOFACE else '',
                         label(r['main']), '%d%%' % (r['main_ratio'] * 100),
                         ' '.join('%s%d%%' % (label(i), p * 100) for i, p in r['top']),
                         '%d%%' % (r['highlight'] * 100), '?' if r['uncertain'] else '', new, ''])


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
    while os.path.exists(log_path) or os.path.exists(log_path[:-4] + '_已復原.csv'):  # 同一秒內再執行也不撞名
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
    logs = [f for f in os.listdir(folder)
            if f.startswith((LOG_PREFIX, '_色彩改名紀錄_')) and f.endswith('.csv') and '已復原' not in f]
    if not logs:
        return None

    def order(f):  # 最新的排最後：依修改時間，同時間再依檔名裡的序號（_2、_10…）
        m = re.search(r'_(\d+)_(\d+)(?:_(\d+))?\.csv$', f)
        seq = (m.group(1), m.group(2), int(m.group(3) or 1)) if m else ('', '', 0)
        return (os.path.getmtime(os.path.join(folder, f)), seq)
    return os.path.join(folder, max(logs, key=order))


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
    done_path, k = log_path[:-4] + '_已復原.csv', 1
    while os.path.exists(done_path):  # 不覆蓋舊的已復原紀錄
        k += 1
        done_path = log_path[:-4] + '_已復原_%d.csv' % k
    os.rename(log_path, done_path)
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
    root.geometry('1320x720')

    folder = tk.StringVar()
    recursive = tk.BooleanVar(value=False)
    output = tk.StringVar(value='rename')
    mode = tk.StringVar(value='both')
    order = tk.StringVar(value='skin')
    digits = tk.BooleanVar(value=True)
    performer = tk.BooleanVar(value=False)
    sort_by = tk.StringVar(value='time')
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

    opts2 = ttk.Frame(root, padding=(8, 4, 8, 0))
    opts2.pack(fill='x')
    ttk.Checkbutton(opts2, text='整體偏重演出者（背景 LED 螢幕很花時勾選）', variable=performer,
                    command=on_option).pack(side='left')
    ttk.Label(opts2, text='　　表格排序：').pack(side='left')
    for t, v in (('拍攝時間', 'time'), ('檔名', 'name'), ('顏色', 'color')):
        ttk.Radiobutton(opts2, text=t, value=v, variable=sort_by, command=on_option).pack(side='left')

    ttk.Label(root, padding=(8, 4), foreground='#555',
              text='顏色：0白(白光/自然膚色) 1紅 2橙 3黃 4綠 5青 6藍 7紫 8粉 9暗 無(沒偵測到臉)'
                   '　｜　改檔名例：6藍7紫_原檔名 → 前面是優先項目，後面是另一項'
                   '\n段落：照拍攝時間切開的同燈光區段　★：該段代表張（先修這張再同步）　'
                   '清晰度：整批相對分數 0~100　?：主色票數偏低，建議人工確認').pack(fill='x')

    btns = ttk.Frame(root, padding=8)
    btns.pack(fill='x')
    b_analyze = ttk.Button(btns, text='① 分析（預覽，不動檔案）', command=lambda: start_analysis())
    b_apply = ttk.Button(btns, text='② 執行改名', command=lambda: do_apply())
    b_undo = ttk.Button(btns, text='復原上一次', command=lambda: do_undo())
    b_strip = ttk.Button(btns, text='移除所有顏色前綴', command=lambda: do_strip())
    b_csv = ttk.Button(btns, text='匯出 CSV', command=lambda: do_export())
    for b in (b_analyze, b_apply, b_undo, b_strip, b_csv):
        b.pack(side='left', padx=4)
    pbar = ttk.Progressbar(btns, length=250)
    pbar.pack(side='right')

    # --- 預覽表格
    cols = ('file', 'time', 'scene', 'rep', 'sharp', 'faces', 'skin', 'skin_r', 'main', 'main_r', 'top', 'hl', 'new')
    heads = ('原檔名', '拍攝時間', '段落', '代表', '清晰度', '臉數', '膚色', '膚色比例', '整體', '整體比例',
             '整體組成', '燈光爆點', '結果')
    widths = (170, 95, 45, 40, 55, 40, 45, 65, 50, 65, 160, 65, 300)
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
        for w in (b_analyze, b_apply, b_undo, b_strip, b_csv):
            w.state(['disabled'] if b else ['!disabled'])
        if not b and output.get() == 'folder':
            b_strip.state(['disabled'])

    def current_rows():
        """套用目前選項後的結果（含挑圖資訊），依表格排序方式排好"""
        rows = batch_features(state['results'], mode.get(), order.get(), performer.get())
        sk = slot_order(mode.get(), order.get())
        if sort_by.get() == 'name':
            rows.sort(key=lambda r: (r['dir'], r['stem']))
        elif sort_by.get() == 'color':
            rows.sort(key=lambda r: (1, r['source']) if r.get('error') else
                      (0, build_prefix(r, mode.get(), order.get(), True), r['time']))
        return rows, sk[0]

    def refresh_table():
        tree.delete(*tree.get_children())
        rows, sort_key = current_rows()
        for r in rows:
            if r.get('error'):
                tree.insert('', 'end', values=(r['source'], '', '', '', '', '', '錯誤', '', '', '', r['error'], '', ''),
                            tags=('err',))
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
            t = r['time'].strftime('%H:%M:%S') + ('' if r['time_src'] == 'EXIF' else '*')
            tree.insert('', 'end', tags=('c%d' % r[sort_key],), values=(
                r['source'], t, 'S%02d' % r['scene'], '★' if r['rep'] else '', r['sharp_score'],
                r['faces'], label(r['skin']),
                '%d%%' % (r['skin_ratio'] * 100) if r['skin'] != NOFACE else '',
                label(r['main']) + ('?' if r['uncertain'] else ''), '%d%%' % (r['main_ratio'] * 100), top3,
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
        plan = plan_renames([effective(r, performer.get()) for r in state['results']],
                            mode.get(), order.get(), digits.get(), output.get())
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

    def do_export():
        f = check_folder()
        if not f:
            return
        if not state['results']:
            messagebox.showinfo('提示', '請先按「① 分析」')
            return
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        path, k = os.path.join(f, '_色彩分析_%s.csv' % stamp), 1
        while os.path.exists(path):  # 同一秒內重複匯出不覆蓋
            k += 1
            path = os.path.join(f, '_色彩分析_%s_%d.csv' % (stamp, k))
        try:
            rows, _ = current_rows()
            export_csv(rows, path, mode.get(), order.get(), digits.get(), output.get())
        except Exception as e:
            messagebox.showerror('無法匯出', str(e))
            return
        status.set('已匯出：%s' % os.path.basename(path))
        messagebox.showinfo('完成', '已匯出到資料夾內：\n%s\n\n可以用 Excel 開啟。' % os.path.basename(path))

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
    ap.add_argument('--performer', action='store_true', help='整體偏重演出者（背景 LED 螢幕很花時使用）')
    ap.add_argument('--csv', metavar='PATH', help='把分析結果（含挑圖資訊）存成 CSV')
    a = ap.parse_args(argv)

    if not os.path.isdir(a.folder):
        print('找不到資料夾：%s' % a.folder)
        sys.exit(2)
    groups = collect_groups(a.folder, a.recursive)
    print('共 %d 張，分析中…' % len(groups))
    results = run_analysis(groups, progress=lambda i, n: print('\r%d/%d' % (i, n), end='', flush=True))
    print()
    rows = batch_features(results, a.mode, a.order, a.performer)
    for r in rows:
        if r.get('error'):
            print('[錯誤] %s：%s' % (r['source'], r['error']))
        else:
            print('%-40s %s S%02d%s 清晰:%3d 臉:%d 膚色:%s(%d%%) 整體:%s%s(%d%%) 爆點:%d%%' % (
                r['source'], r['time'].strftime('%H:%M:%S') + ('' if r['time_src'] == 'EXIF' else '*'),
                r['scene'], '★' if r['rep'] else ' ', r['sharp_score'], r['faces'], label(r['skin']),
                r['skin_ratio'] * 100, label(r['main']), '?' if r['uncertain'] else '', r['main_ratio'] * 100,
                r.get('highlight', 0) * 100))
    if a.csv:
        export_csv(rows, a.csv, a.mode, a.order, not a.no_digits, a.output)
        print('已匯出 CSV：%s' % a.csv)
    plan = plan_renames(rows, a.mode, a.order, not a.no_digits, a.output)
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
