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
              [--performer] [--csv 結果.csv] [--time-seq] [--report [報告.txt]]
              [--stage standard|pale] [--scenes auto|manual|both --splits "2921,3040"]
  還原修圖後檔名：python photo_color_sorter.py <輸出資料夾> --restore [--log-folder 原始資料夾] [--apply]
"""
import os
import re
import csv
import sys
import queue
import argparse
import json
import struct
import hashlib
import datetime
import threading
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import cv2

__version__ = '1.4.0'

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

# 顏色小方塊與圖例用的鮮明色（表格底色用下面較淡的 TAG_COLORS）
SWATCH_COLORS = ['#e5484d', '#f08c24', '#e9c71a', '#3aa655', '#25b5c4', '#3a6fe0',
                 '#8a4fd6', '#ec6fb8', '#f2f2f2', '#555555', '#ffffff']

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
BRIGHT_EV = (-0.5, -1.5)  # 亮度分組：和參考亮度相差 0.5 級內為亮、1.5 級內為中，更暗為暗
STAR_BLUR_SCORE = 15      # 自動評分：清晰度在整批最後 15%，而且……
BLUR_RATIO = 0.9          # ……清晰度低於整批中位數的 90%，才算可能模糊（整批都清楚時不會硬挑出模糊照）
BLUR_RATIO_STRONG = 0.7   # 低於整批中位數的 70% 時，不論排名都算可能模糊
DARK_FACE = 0.12          # 臉部亮度低於此值：太暗，清晰度不可靠，評分理由寫「臉太暗」
GRAY_FACE_CHROMA = 3      # 臉的色度低於此值視為黑白照片，不給調色建議
WB_MIN_SHIFT = 4          # 調色起點：臉的色偏小於此值（Lab 色度差）視為正常
SKIN_NATURAL_S = 0.62     # 膚色：在膚色色相範圍內且飽和度低於此值 = 自然光
SKIN_NATURAL_HUE = (5, 40)
SKIN_NEUTRAL_S = 0.12     # 膚色：飽和度低於此值一律算自然光

# 舞台顏色濃淡：手動選擇。「淡」適合整場燈光顏色很淡的舞台，代價是真正的白光場景容易被判成有色
STAGE_PRESETS = {
    'standard': dict(DARK_V=0.12, NEUTRAL_S=0.25, NEUTRAL_MIN_V=0.35, SKIN_NATURAL_S=0.62,
                     SKIN_NATURAL_HUE=(5, 40), SKIN_NEUTRAL_S=0.12),
    'pale': dict(DARK_V=0.15, NEUTRAL_S=0.14, NEUTRAL_MIN_V=0.30, SKIN_NATURAL_S=0.42,
                 SKIN_NATURAL_HUE=(8, 35), SKIN_NEUTRAL_S=0.08),
}
STAGE_NAMES = {'standard': '標準', 'pale': '淡色舞台'}


# 挑圖功能開關（進階設定）。關掉的功能不顯示；人物分組關掉時連臉部特徵都不計算，分析較快
FEATURES = ('rep', 'stars', 'person', 'bright', 'wb', 'timeline')
FEATURE_NAMES = {'rep': '代表張', 'stars': '星等', 'person': '人物分組', 'bright': '亮度分組',
                 'wb': '調色起點', 'timeline': '燈光時間軸'}
ALL_FEATURES = {k: True for k in FEATURES}
SETTINGS_PATH = os.path.join(os.path.expanduser('~'), '.photo_color_sorter.json')


def load_settings(path=None):
    """讀取上次的進階設定；檔案不存在或壞掉時回傳空設定"""
    try:
        with open(path or SETTINGS_PATH, encoding='utf-8') as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data, path=None):
    try:
        with open(path or SETTINGS_PATH, 'w', encoding='utf-8') as fp:
            json.dump(data, fp, ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


def apply_stage_preset(name='standard'):
    globals().update(STAGE_PRESETS.get(name, STAGE_PRESETS['standard']))

_COLOR_CHARS = ''.join(c[1] for c in CATEGORIES)
# 新格式（可帶時間序號，例如 8粉_0012_）| 舊版長格式
PREFIX_RE = re.compile(r'^(?:(?:\d?[%s]){1,2}_(?:\d{4,6}_)?|(?:[SM]\d{2}[^_]*_){1,2}_)' % _COLOR_CHARS)
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
SFACE_MODEL = os.path.join(APP_DIR, 'face_recognition_sface_2021dec_int8.onnx')  # 人物分組用（選配）
SFACE_SHA256 = '2b0e941e6f16cc048c20aee0c8e31f569118f65d702914540f7bfdc14048d78a'
SAME_PERSON_COS = 0.363  # SFace：兩張臉特徵的相似度超過此值視為同一人（OpenCV 官方建議值）
FACE_SCORE = 0.7         # YuNet 人臉信心門檻，誤判多就調高、漏抓多就調低
DETECT_SIDE = 1920        # 偵測用解析度，遠景小臉需要較高解析度

_cascades = None
_yunet = None
_sface = None


class Face(tuple):
    """(x, y, w, h, 信心)，另外帶著 YuNet 的五官位置（raw），人物分組對齊臉部時使用"""
    raw = None


def _get_sface():
    """人臉辨識模型（只判斷兩張臉像不像，不辨識身分）；沒有模型檔或驗證失敗時回傳 False，人物分組就略過"""
    global _sface
    if _sface is None:
        _sface = False
        try:
            if os.path.exists(SFACE_MODEL) and hasattr(cv2, 'FaceRecognizerSF'):
                data = np.fromfile(SFACE_MODEL, np.uint8)
                if hashlib.sha256(data.tobytes()).hexdigest() == SFACE_SHA256:
                    _sface = cv2.FaceRecognizerSF.create('onnx', data, np.array([], np.uint8))
        except Exception:
            _sface = False
    return _sface


def sface_available():
    return bool(_get_sface())


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
        out = []
        for f in faces:
            if min(f[2], f[3]) >= 10:
                face = Face((int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[14])))
                face.raw = f.copy()
                out.append(face)
        return out
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
        natural = (s < SKIN_NEUTRAL_S) | ((h >= SKIN_NATURAL_HUE[0]) & (h < SKIN_NATURAL_HUE[1]) & (s < SKIN_NATURAL_S))
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
        imgs = sorted(imgs)
        source = (imgs or raws)[0]  # 有 JPG 就用 JPG（較快）
        # 同名但格式不同的「照片」（例如 x.jpg 與 x.png）是不同的照片，各自分析；
        # RAW、XMP 只跟第一張照片配對（相機的 RAW+JPG 同名檔）
        others = imgs[1:]
        main_files = [f for f in files if f not in others]
        result.append({'dir': d, 'stem': stem, 'files': sorted(main_files), 'source': source})
        for f in others:
            result.append({'dir': d, 'stem': stem, 'files': [f], 'source': f})
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


def face_embedding(work, faces):
    """最大那張臉的特徵向量（128 維，已正規化），用來判斷是不是同一人；沒有模型或沒有臉時回傳 None"""
    rec = _get_sface()
    if not rec or not faces:
        return None
    f = max(faces, key=lambda x: x[2] * x[3])
    if getattr(f, 'raw', None) is None:
        return None  # Haar 偵測沒有五官位置，無法對齊
    try:
        emb = rec.feature(rec.alignCrop(work, f.raw)).flatten().astype(np.float32)
        n = float(np.linalg.norm(emb))
        return (emb / n).tolist() if n > 0 else None
    except Exception:
        return None


def face_lab(work, faces):
    """最大那張臉中央的 Lab 色度 (a, b)：a 正 = 偏洋紅、負 = 偏綠；b 正 = 偏黃、負 = 偏藍"""
    if not faces:
        return None
    x, y, w, h, _ = max(faces, key=lambda f: f[2] * f[3])
    mask = np.zeros(work.shape[:2], np.uint8)
    cv2.ellipse(mask, (int(x + w / 2), int(y + h * 0.55)), (int(w * 0.32), int(h * 0.36)), 0, 0, 360, 255, -1)
    sel = mask > 0
    if sel.sum() < 20:
        return None
    ys, xs = np.nonzero(sel)  # 只轉換臉部範圍，不轉整張圖
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    lab = cv2.cvtColor(work[y0:y1, x0:x1], cv2.COLOR_BGR2LAB)[sel[y0:y1, x0:x1]].astype(np.float32)
    return float(np.median(lab[:, 1]) - 128), float(np.median(lab[:, 2]) - 128)


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


def analyze_group(group, stage='standard', person=True):
    apply_stage_preset(stage)
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
        emb = face_embedding(work, faces) if person else None
        ab = face_lab(work, faces)
        t, t_src = group_capture_time(group)
        return dict(group, skin=skin, skin_ratio=skin_ratio, faces=nfaces,
                    main=main, main_ratio=main_ratio, top=top, highlight=highlight,
                    main_perf=main_p, main_perf_ratio=main_p_ratio, top_perf=top_p,
                    sharp=sharp, face_px=face_px, face_bright=face_bright, face_emb=emb, face_ab=ab,
                    time=t, time_src=t_src, stage=stage, error=None)
    except Exception as e:
        return dict(group, error=friendly_error(e))


def friendly_error(e):
    """把程式內部的錯誤訊息換成看得懂的說明"""
    msg = str(e)
    if 'Unsupported file format' in msg or 'not RAW file' in msg:
        return '不支援的 RAW 格式，或檔案已損壞'
    if isinstance(e, MemoryError):
        return '圖片太大，記憶體不足'
    if isinstance(e, (FileNotFoundError, PermissionError)):
        return '無法開啟檔案（可能已被移動、刪除或沒有權限）'
    if isinstance(e, cv2.error) or 'buf.empty' in msg or '無法讀取圖片' in msg:
        return '無法讀取圖片（檔案可能損壞、是空檔，或不是真的圖片）'
    if 'rawpy' in msg:
        return msg
    return '分析失敗：%s' % msg.splitlines()[0][:120] if msg else '分析失敗'


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


def file_number(stem):
    """檔名裡最後一段數字，例如 DSC02921 -> 2921、IMG_9699 -> 9699；沒有數字時回傳 None"""
    nums = re.findall(r'\d+', stem)
    return int(nums[-1]) if nums else None


def parse_splits(text):
    """把使用者輸入的分段號碼（例如「2921, 3040 3074」）轉成數字清單"""
    return sorted({int(x) for x in re.findall(r'\d+', text or '')})


def match_splits(ok, splits):
    """在照時間排好的照片中，找出每個分段號碼對應的位置。
    完全相同的號碼優先；沒有時用號碼比它大、最接近的那張。回傳 (位置集合, 對不到的號碼)"""
    nums = [file_number(r['stem']) for r in ok]
    idx, missing = set(), []
    for v in splits:
        exact = [i for i, n in enumerate(nums) if n == v]
        if exact:
            idx.add(exact[0])
            continue
        bigger = [(n, i) for i, n in enumerate(nums) if n is not None and n > v]
        if bigger:
            idx.add(min(bigger)[1])
        else:
            missing.append(v)
    idx.discard(0)
    return idx, missing


def batch_features(results, mode='both', order='skin', performer=False, scene_mode='auto', splits=()):
    """整批照片的挑圖資訊：依拍攝時間排序、切燈光段落、清晰度分數（0~100，整批相對）、每段代表張。
    scene_mode：'auto' 自動切段；'manual' 只依 splits（檔名號碼，從這張開始新段落）；'both' 兩者都切。
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
    auto_starts = {start for start, _ in merged}
    manual_starts, _ = match_splits(ok, splits) if splits else (set(), [])
    if scene_mode == 'manual':
        starts = {0} | manual_starts
    elif scene_mode == 'both':
        starts = auto_starts | manual_starts
    else:
        starts = auto_starts
    seg, k = [], -1
    for i in range(len(ok)):
        if i in starts or i == 0:
            k += 1
        seg.append(k)
    out = []
    seq_w = max(4, len(str(len(ok))))
    for i, r in enumerate(ok):
        out.append(dict(r, scene=seg[i] + 1, seq=i + 1, seq_w=seq_w,
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
    _assign_persons(out)
    _assign_brightness(out)
    _assign_stars(out)
    _assign_wb(out)
    return out + bad


def _assign_persons(rows):
    """人物分組：依拍攝時間逐張比對每一組的平均臉部特徵，相似度夠高就歸同一人，否則開新的一組。
    組別依照片數多到少命名 P1、P2…；沒有臉或沒有模型時為 None。"""
    centers, members = [], []
    for i, r in enumerate(rows):
        e = r.get('face_emb')
        r['person'] = None
        if e is None:
            continue
        e = np.asarray(e, np.float32)
        if centers:
            sims = np.array([float(c @ e) / max(float(np.linalg.norm(c)), 1e-9) for c in centers])
            k = int(sims.argmax())
            if sims[k] >= SAME_PERSON_COS:
                centers[k] = centers[k] + e
                members[k].append(i)
                continue
        centers.append(e.copy())
        members.append([i])
    order = sorted(range(len(members)), key=lambda k: (-len(members[k]), members[k][0]))
    for rank, k in enumerate(order, 1):
        for i in members[k]:
            rows[i]['person'] = 'P%d' % rank


def _linear(v):
    return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92


def _assign_brightness(rows):
    """亮度分組（亮／中／暗）：和同一個人最亮的幾張比（沒有人物分組時和整批比），
    差 0.5 級以內為亮、1.5 級以內為中、更暗為暗。舞台上同一首歌追光忽亮忽暗時，可以分開同步。"""
    def ref_of(vals):
        return float(np.percentile(vals, 90)) if vals else None
    lin = {i: _linear(r['face_bright']) for i, r in enumerate(rows) if r.get('face_bright')}
    all_ref = ref_of(list(lin.values()))
    by_person = {}
    for i, r in enumerate(rows):
        if i in lin and r.get('person'):
            by_person.setdefault(r['person'], []).append(lin[i])
    refs = {p: ref_of(v) for p, v in by_person.items() if len(v) >= 3}
    for i, r in enumerate(rows):
        r['bright'], r['ev'] = None, None
        if i not in lin or not all_ref:
            continue
        ref = refs.get(r.get('person'), all_ref)
        ev = float(np.log2(max(lin[i], 1e-6) / max(ref, 1e-6)))
        r['ev'] = ev
        r['bright'] = '亮' if ev >= BRIGHT_EV[0] else '中' if ev >= BRIGHT_EV[1] else '暗'


def _assign_stars(rows):
    """自動評分 1~3 星（整批相對，用來初篩）：
    1 星 = 沒有臉、臉太暗，或可能模糊（清晰度在整批最後 15% 且低於整批中位數的 90%，或低於 70%）；
    3 星 = 清晰度前段（≥50）、臉不小於整批中位數、亮度為亮或中、臉沒有過曝或太暗；其餘 2 星。"""
    sizes = [r['face_px'] for r in rows if r['faces']]
    med = float(np.median(sizes)) if sizes else 0.0
    sharp_med = float(np.median([r['sharp'] for r in rows])) if rows else 0.0
    for r in rows:
        ratio = r['sharp'] / sharp_med if sharp_med > 0 else 1.0
        fb = r.get('face_bright')
        too_dark = fb is not None and fb < DARK_FACE
        # 臉偏暗（< 0.2）時細節被壓掉，清晰度不可靠，不判模糊（改在 2 星理由寫「臉太暗」）
        blurry = (ratio < BLUR_RATIO_STRONG or (r['sharp_score'] < STAR_BLUR_SCORE and ratio < BLUR_RATIO)) \
            and not (fb is not None and fb < 0.2)
        if not r['faces'] or too_dark or blurry:
            r['stars'], r['star_why'] = 1, '沒有臉' if not r['faces'] else '臉太暗' if too_dark else '可能模糊'
        elif (r['sharp_score'] >= 50 and r['face_px'] >= med and r.get('bright') in ('亮', '中')
              and r.get('face_bright') is not None and 0.2 <= r['face_bright'] <= 0.9):
            r['stars'], r['star_why'] = 3, ''
        else:
            why = []
            if r['sharp_score'] < 50:
                why.append('清晰度普通')
            if r['face_px'] < med:
                why.append('臉偏小')
            if r.get('bright') == '暗':
                why.append('偏暗')
            fb = r.get('face_bright')
            if fb is not None and not 0.2 <= fb <= 0.9:
                why.append('臉過曝' if fb > 0.9 else '臉太暗')
            r['stars'], r['star_why'] = 2, '、'.join(why)


def _assign_wb(rows):
    """調色起點建議：臉的顏色和「同一個人在自然光下的膚色」比，偏了多少、往哪個方向。
    只給方向與相對強度（Lab 色度差），不寫入檔案；數值不是 Lightroom 滑桿的精確值。
    色溫為負 = 往冷（藍）調，正 = 往暖（黃）調；色調為負 = 往綠調，正 = 往洋紅調。"""
    natural = [r for r in rows if r.get('face_ab') and r['skin'] == WHITE]
    def med_ab(rs):
        return (float(np.median([r['face_ab'][0] for r in rs])), float(np.median([r['face_ab'][1] for r in rs]))) if rs else None
    all_ref = med_ab(natural)
    by_person = {}
    for r in natural:
        if r.get('person'):
            by_person.setdefault(r['person'], []).append(r)
    refs = {p: med_ab(v) for p, v in by_person.items() if len(v) >= 2}
    for r in rows:
        r['wb_temp'] = r['wb_tint'] = r['wb_shift'] = None
        ref = refs.get(r.get('person'), all_ref)
        if not r.get('face_ab') or ref is None:
            continue
        if float(np.hypot(*r['face_ab'])) < GRAY_FACE_CHROMA:
            continue  # 黑白照片：臉沒有顏色，不給調色建議
        da, db = r['face_ab'][0] - ref[0], r['face_ab'][1] - ref[1]
        r['wb_shift'] = float(np.hypot(da, db))
        r['wb_temp'], r['wb_tint'] = -db, -da


def wb_text(r):
    """調色起點建議的文字，例如「色溫−9 色調−6」；偏差很小時回傳「—」"""
    if r.get('wb_shift') is None:
        return ''
    if r['wb_shift'] < WB_MIN_SHIFT:
        return '—'
    return '色溫%+d 色調%+d' % (round(r['wb_temp']), round(r['wb_tint']))


def build_report(rows, mode='both', order='skin', performer=False, features=None):
    """分析報告：整批結果的統計，以及需要注意的地方。回傳 (摘要行清單, 提醒清單)。
    提醒依「⚠ 需要注意」與「ℹ 參考」分級，讓使用者知道這次的結果可不可靠、該怎麼調。"""
    ok = [r for r in rows if not r.get('error')]
    bad = [r for r in rows if r.get('error')]
    n = len(ok)
    lines, notes = [], []
    on = dict(ALL_FEATURES, **(features or {}))
    pct = lambda k: 100.0 * k / n if n else 0.0
    lines.append('照片：%d 張成功分析%s' % (n, '，%d 張讀取失敗' % len(bad) if bad else ''))
    if not n:
        notes.append('⚠ 沒有任何照片分析成功，請確認資料夾裡是支援的照片格式')
        return lines, notes
    def dist(key):
        c = {}
        for r in ok:
            c[r[key]] = c.get(r[key], 0) + 1
        return '、'.join('%s %d' % (label(k), v) for k, v in sorted(c.items(), key=lambda kv: -kv[1]))
    lines.append('整體主色：' + dist('main'))
    lines.append('膚色：' + dist('skin'))
    exif = sum(r['time_src'] == 'EXIF' for r in ok)
    lines.append('拍攝時間：%d 張讀到 EXIF（%.0f%%）' % (exif, pct(exif)))
    scenes = len({r['scene'] for r in ok})
    lines.append('燈光段落：%d 段，每段平均 %.1f 張' % (scenes, n / max(scenes, 1)))
    persons = {r['person'] for r in ok if r.get('person')}
    with_face = [r for r in ok if r['faces']]
    person_on = on['person'] and sface_available()
    if not on['person']:
        pass
    elif not sface_available():
        lines.append('人物分組：沒有人臉辨識模型，已略過')
    else:
        lines.append('人物分組：%d 組（%d 張有臉）' % (len(persons), len(with_face)))
    stars = {s: sum(r['stars'] == s for r in ok) for s in (3, 2, 1)}
    if on['stars']:
        lines.append('自動評分：3 星 %d、2 星 %d、1 星 %d' % (stars[3], stars[2], stars[1]))
    br = {b: sum(r.get('bright') == b for r in ok) for b in ('亮', '中', '暗')}
    if on['bright']:
        lines.append('亮度分組：亮 %d、中 %d、暗 %d' % (br['亮'], br['中'], br['暗']))
    shifted = [r for r in ok if r.get('wb_shift') is not None and r['wb_shift'] >= WB_MIN_SHIFT]
    has_ref = any(r.get('wb_shift') is not None for r in ok)
    if not on['wb']:
        pass
    elif not with_face:
        lines.append('調色起點：沒有偵測到臉，無法建議')
    elif not has_ref:
        lines.append('調色起點：沒有在自然光下的臉可當基準，無法建議（每張臉都被色光照到，或是黑白照片）')
    else:
        lines.append('調色起點：%d 張的臉有明顯色偏，建議先調白平衡' % len(shifted))
    off = [FEATURE_NAMES[k] for k in FEATURES if not on[k]]
    if off:
        lines.append('已關閉：' + '、'.join(off))

    white = sum(r['main'] == WHITE for r in ok)
    unc = sum(r['uncertain'] for r in ok)
    noface = n - len(with_face)
    if bad:
        notes.append('⚠ %d 張讀取失敗（表格中紅色列），其他照片不受影響' % len(bad))
    stage = ok[0].get('stage', 'standard')
    if n >= 10 and pct(white) >= 60:
        notes.append('⚠ %.0f%% 的照片整體判成白：可能是白光為主或顏色很淡的舞台。可以改用「只看膚色」，'
                     '或在進階設定把「舞台顏色」改成「淡色舞台」再分析一次比較' % pct(white)
                     if stage == 'standard' else
                     '⚠ %.0f%% 的照片整體判成白：已經是「淡色舞台」設定，這批多半真的是白光' % pct(white))
    if stage == 'pale':
        warm_faces = sum(r['skin'] in (0, 1) for r in with_face)
        if len(with_face) >= 5 and warm_faces >= 0.4 * len(with_face):
            notes.append('⚠ 「淡色舞台」設定下有 %d 張臉被判成紅或橙：膚色本身被當成色光了，建議改回「標準」'
                         % warm_faces)
        else:
            notes.append('ℹ 目前使用「淡色舞台」設定：顏色淡的燈光比較抓得到，但真正的白光場景容易被判成有色')
    if n >= 10 and pct(unc) >= 40:
        if performer:
            notes.append('⚠ %.0f%% 的照片主色票數偏低（?）：已經勾了「整體偏重演出者」仍然偏低，代表打在人身上的光本身就很雜，'
                         '建議改用「只看膚色」，或人工確認標「?」的照片' % pct(unc))
        else:
            notes.append('⚠ %.0f%% 的照片主色票數偏低（?）：畫面顏色很雜，背景 LED 螢幕很花時可以勾「整體偏重演出者」' % pct(unc))
    if n >= 5 and pct(noface) >= 50:
        notes.append('⚠ %.0f%% 的照片沒偵測到臉：膚色、人物分組、亮度與評分會較少，建議以「只看整體」分類' % pct(noface))
    if exif == 0:
        notes.append('ℹ 沒有讀到任何拍攝時間（可能是截圖、轉存或社群下載的照片），段落與時間序號改用檔案時間，順序可能不準')
    elif exif < n:
        notes.append('ℹ %d 張沒有拍攝時間，改用檔案時間（表格時間後面有 *）' % (n - exif))
    if person_on and len(with_face) >= 10:
        size = {}
        for r in ok:
            if r.get('person'):
                size[r['person']] = size.get(r['person'], 0) + 1
        small = [k for k, v in size.items() if v <= 2]
        if len(small) >= 2:
            notes.append('ℹ 人物分組有 %d 組只有 1～2 張，可能是同一人被拆開（濃妝、側臉、臉太小或模糊），可以用「表格排序：人物」人工確認'
                         % len(small))
    blur1 = sum(r['stars'] == 1 and r.get('star_why') == '可能模糊' for r in ok)
    if on['stars'] and n >= 10 and blur1 >= 0.3 * n:
        notes.append('ℹ %d 張被評為可能模糊（%.0f%%）：如果現場本來就很暗或有大量動態，可以改看清晰度數字挑選' % (blur1, pct(blur1)))
    if scenes >= 0.6 * n and n >= 10:
        notes.append('ℹ 段落很碎（%d 張分成 %d 段）：燈光變化很快，或拍攝時間不連續' % (n, scenes))
    if not notes:
        notes.append('✓ 沒有發現異常')
    return lines, notes


def report_text(rows, mode='both', order='skin', folder=None, performer=False, features=None):
    lines, notes = build_report(rows, mode, order, performer, features)
    head = ['舞台照片色彩分類工具 v%s 分析報告' % __version__,
            '時間：%s' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
    if folder:
        head.append('資料夾：%s' % folder)
    return '\n'.join(head + [''] + lines + ['', '需要注意：'] + notes) + '\n'


def export_csv(rows, path, mode='both', order='skin', digits=True, output='rename', time_seq=False, features=None):
    """把分析結果（含挑圖資訊）存成 CSV，可用 Excel 開啟；關掉的挑圖功能欄位留空"""
    on = dict(ALL_FEATURES, **(features or {}))
    with open(path, 'w', newline='', encoding='utf-8-sig') as fp:
        wr = csv.writer(fp)
        wr.writerow(['檔名', '拍攝時間', '時間來源', '燈光段落', '代表張', '清晰度', '星等', '評分說明', '人物', '亮度',
                     '調色起點建議', '臉數', '膚色', '膚色比例', '整體', '整體比例', '整體組成', '燈光爆點', '不確定',
                     '結果', '錯誤'])
        for r in rows:
            if r.get('error'):
                wr.writerow([r['source']] + [''] * 19 + [r['error']])
                continue
            clean = strip_prefix(r['source'])
            new = (os.path.join(build_subdir(r, mode, order, digits), clean) if output == 'folder'
                   else build_prefix(r, mode, order, digits, time_seq) + clean)
            wr.writerow([r['source'], r['time'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], r['time_src'],
                         'S%02d' % r['scene'], '★' if r['rep'] and on['rep'] else '', r['sharp_score'],
                         r.get('stars', '') if on['stars'] else '', r.get('star_why', '') if on['stars'] else '',
                         (r.get('person') or '') if on['person'] else '', (r.get('bright') or '') if on['bright'] else '',
                         wb_text(r) if on['wb'] else '', r['faces'],
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


def build_prefix(res, mode='both', order='skin', digits=True, time_seq=False):
    """檔名前綴，例如 6藍7紫_（前 = 排序優先的那一項）。
    time_seq=True 時再加拍攝時間序號，例如 8粉_0012_：同色的照片照拍攝時間排，不受原檔名編號影響"""
    p = ''.join(tag(res[k], digits) for k in slot_order(mode, order)) + '_'
    if time_seq and res.get('seq'):
        p += '%0*d_' % (res.get('seq_w', 4), res['seq'])
    return p


def build_subdir(res, mode='both', order='skin', digits=True):
    """分資料夾路徑，例如 膚色6藍/整體7紫"""
    names = {'skin': '膚色', 'main': '整體'}
    return os.path.join(*[names[k] + tag(res[k], digits) for k in slot_order(mode, order)])


def plan_renames(results, mode='both', order='skin', digits=True, output='rename', time_seq=False):
    """回傳 [(舊完整路徑, 新完整路徑)]。output='rename' 改檔名，'folder' 移到顏色子資料夾。
    time_seq 需要 batch_features 算好的 seq（拍攝時間順序），只用於改檔名"""
    plan = []
    for r in results:
        if r.get('error'):
            continue
        for f in r['files']:
            clean = strip_prefix(f)
            if output == 'folder':
                new = os.path.join(r['dir'], build_subdir(r, mode, order, digits), clean)
            else:
                new = os.path.join(r['dir'], build_prefix(r, mode, order, digits, time_seq) + clean)
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


def _log_mappings(folders):
    """從改名紀錄讀出 {改名後的主檔名: 原本的主檔名}（只取「改檔名」的紀錄，分資料夾的沒有改名）"""
    mapping = {}
    for d in folders:
        if not d or not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if not (f.startswith((LOG_PREFIX, '_色彩改名紀錄_')) and f.endswith('.csv')):
                continue
            try:
                with open(os.path.join(d, f), newline='', encoding='utf-8-sig') as fp:
                    for row in csv.DictReader(fp):
                        old, new = row.get('old'), row.get('new')
                        if not old or not new:
                            continue
                        if os.path.dirname(os.path.abspath(old)) != os.path.dirname(os.path.abspath(new)):
                            continue
                        o, n = file_stem(os.path.basename(old)), file_stem(os.path.basename(new))
                        if o != n:
                            mapping[n] = o
            except Exception:
                continue  # 讀不了的紀錄檔就略過
    # 執行過好幾次時，紀錄是「第二次的名字 → 第一次的名字」；和改名時一樣移除前綴，就回到最原始的名字
    return {n: strip_prefix(o) for n, o in mapping.items()}


def plan_restore(folder, log_folders=(), recursive=False):
    """修圖輸出後還原原本的檔名，例如
         8粉_0012_DSC02921-Enhanced-NR.jpg  ->  DSC02921-Enhanced-NR.jpg
    先比對改名紀錄（所選資料夾，以及原始照片所在的資料夾）：檔名開頭是當初改出來的名字，
    就換回原本的名字，後面修圖軟體加的字照樣保留。找得到紀錄時只動紀錄裡的照片，
    其他檔案（例如自己取名的 白_婚禮.jpg）不碰；完全沒有紀錄時，才用前綴規則移除顏色前綴。
    回傳 ([(舊路徑, 新路徑)], 依紀錄還原的數量)"""
    mapping = _log_mappings([folder] + list(log_folders))
    keys = sorted(mapping, key=len, reverse=True)  # 最長的先比，避免 DSC_1 搶走 DSC_10
    plan, by_log = [], 0
    for d, names in walk_photos(folder, recursive):
        for n in names:
            if os.path.splitext(n)[1].lower() not in PHOTO_EXTS:
                continue
            new = None
            for k in keys:
                if n.startswith(k):
                    new = mapping[k] + n[len(k):]
                    by_log += 1
                    break
            if new is None:
                if mapping:
                    continue  # 有紀錄但對不上：不是本工具改過的，不碰
                new = strip_prefix(n)
            if new != n:
                plan.append((os.path.join(d, n), os.path.join(d, new)))
    return plan, by_log


def run_analysis(groups, progress=None, workers=None, stage='standard', person=True):
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    results = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(analyze_group, g, stage, person) for g in groups]
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
    root.geometry('1180x720')

    folder = tk.StringVar()
    recursive = tk.BooleanVar(value=False)
    output = tk.StringVar(value='rename')
    mode = tk.StringVar(value='both')
    order = tk.StringVar(value='skin')
    digits = tk.BooleanVar(value=True)
    performer = tk.BooleanVar(value=False)
    time_seq = tk.BooleanVar(value=False)
    sort_by = tk.StringVar(value='time')
    stage = tk.StringVar(value='standard')
    scene_mode = tk.StringVar(value='auto')
    splits_text = tk.StringVar(value='')
    show_all = tk.BooleanVar(value=False)
    adv_open = tk.BooleanVar(value=False)
    group_scene = tk.BooleanVar(value=True)
    feat = {k: tk.BooleanVar(value=True) for k in FEATURES}
    status = tk.StringVar(value='請選擇照片資料夾，再按「① 分析」')
    state = {'results': [], 'busy': False, 'person_done': True, 'swatch': {}, 'tl': None}
    q = queue.Queue()

    # 記住上次的設定（存在使用者資料夾的 .photo_color_sorter.json）
    saved = load_settings()
    for var, k in ((output, 'output'), (mode, 'mode'), (order, 'order'), (sort_by, 'sort_by'),
                   (stage, 'stage'), (scene_mode, 'scene_mode')):
        if isinstance(saved.get(k), str):
            var.set(saved[k])
    for var, k in ((digits, 'digits'), (performer, 'performer'), (time_seq, 'time_seq'), (show_all, 'show_all'),
                   (adv_open, 'adv_open'), (group_scene, 'group_scene')):
        if isinstance(saved.get(k), bool):
            var.set(saved[k])
    for k, v in (saved.get('features') or {}).items():
        if k in feat and isinstance(v, bool):
            feat[k].set(v)
    if stage.get() not in STAGE_PRESETS:
        stage.set('standard')

    def features_now():
        return {k: v.get() for k, v in feat.items()}

    def remember():
        save_settings({'output': output.get(), 'mode': mode.get(), 'order': order.get(), 'sort_by': sort_by.get(),
                       'stage': stage.get(), 'scene_mode': scene_mode.get(), 'digits': digits.get(),
                       'performer': performer.get(), 'time_seq': time_seq.get(), 'show_all': show_all.get(),
                       'adv_open': adv_open.get(), 'group_scene': group_scene.get(), 'features': features_now()})

    def on_option():
        apply_columns()
        refresh_table()
        remember()
        is_folder = output.get() == 'folder'
        b_apply.configure(text='② 執行分資料夾' if is_folder else '② 執行改名')
        m_tools.entryconfig(STRIP_LABEL, state='disabled' if is_folder or state['busy'] else 'normal')
        c_seq.state(['disabled'] if is_folder else ['!disabled'])

    def on_feature(k):
        if (k == 'person' and feat['person'].get() and state['results'] and not state['person_done']
                and not state['busy'] and messagebox.askyesno('重新分析', '打開「人物分組」需要重新分析才會有結果，要現在開始嗎？')):
            start_analysis()
        on_option()

    def on_stage():
        if state['results'] and not state['busy'] and messagebox.askyesno(
                '重新分析', '改了「舞台顏色」需要重新分析才會生效，要現在開始嗎？'):
            start_analysis()

    def on_scene():
        refresh_table()
        splits = parse_splits(splits_text.get())
        if scene_mode.get() != 'auto' and state['results'] and splits:
            ok = sorted([r for r in state['results'] if not r.get('error')],
                        key=lambda r: (r['time'], r['dir'], r['stem']))
            _, missing = match_splits(ok, splits)
            status.set('已依 %d 個號碼分段%s' % (len(splits) - len(missing),
                       '；找不到：%s' % '、'.join(map(str, missing)) if missing else ''))

    # --- 選單：不常用的工具收在這裡，畫面保持簡潔
    STRIP_LABEL = '移除所有顏色前綴'
    menubar = tk.Menu(root)
    root.config(menu=menubar)
    m_tools = tk.Menu(menubar, tearoff=0)
    m_tools.add_command(label='分析報告', command=lambda: do_report())
    m_tools.add_command(label='燈光時間軸', command=lambda: do_timeline())
    m_tools.add_command(label='匯出 CSV', command=lambda: do_export())
    m_tools.add_separator()
    m_tools.add_command(label='還原修圖後檔名…', command=lambda: do_restore())
    m_tools.add_command(label=STRIP_LABEL, command=lambda: do_strip())
    menubar.add_cascade(label='工具', menu=m_tools)
    m_view = tk.Menu(menubar, tearoff=0)
    m_view.add_checkbutton(label='顯示進階設定', variable=adv_open, command=lambda: toggle_adv())
    m_view.add_checkbutton(label='顯示所有欄位', variable=show_all, command=lambda: apply_columns())
    menubar.add_cascade(label='顯示', menu=m_view)
    m_help = tk.Menu(menubar, tearoff=0)
    m_help.add_command(label='欄位與顏色說明', command=lambda: show_help())
    menubar.add_cascade(label='說明', menu=m_help)

    # --- 基本設定
    top = ttk.Frame(root, padding=8)
    top.pack(fill='x')
    ttk.Label(top, text='資料夾：').pack(side='left')
    ttk.Entry(top, textvariable=folder, width=60).pack(side='left', padx=4)
    ttk.Button(top, text='選擇…', command=lambda: folder.set(filedialog.askdirectory() or folder.get())).pack(side='left')
    ttk.Checkbutton(top, text='包含子資料夾', variable=recursive).pack(side='left', padx=8)

    basic = ttk.Frame(root, padding=(8, 0))
    basic.pack(fill='x')
    ttk.Label(basic, text='分類依據：').pack(side='left')
    for t, v in (('膚色＋整體', 'both'), ('只看膚色', 'skin'), ('只看整體', 'main')):
        ttk.Radiobutton(basic, text=t, value=v, variable=mode, command=on_option).pack(side='left')
    c_seq = ttk.Checkbutton(basic, text='同色內依拍攝時間排列', variable=time_seq, command=on_option)
    c_seq.pack(side='left', padx=(18, 0))
    b_adv = ttk.Button(basic, text='進階設定 ▸', command=lambda: toggle_adv(flip=True))
    b_adv.pack(side='left', padx=(18, 0))

    # --- 進階設定（預設收起來）
    adv = ttk.LabelFrame(root, text='進階設定', padding=(8, 4))
    a1 = ttk.Frame(adv)
    a1.pack(fill='x')
    ttk.Label(a1, text='輸出方式：').pack(side='left')
    for t, v in (('改檔名', 'rename'), ('分資料夾', 'folder')):
        ttk.Radiobutton(a1, text=t, value=v, variable=output, command=on_option).pack(side='left')
    ttk.Label(a1, text='　優先：').pack(side='left')
    for t, v in (('膚色', 'skin'), ('整體', 'main')):
        ttk.Radiobutton(a1, text=t, value=v, variable=order, command=on_option).pack(side='left')
    ttk.Checkbutton(a1, text='加排序數字', variable=digits, command=on_option).pack(side='left', padx=10)
    ttk.Checkbutton(a1, text='整體偏重演出者（背景 LED 螢幕很花時）', variable=performer,
                    command=on_option).pack(side='left', padx=10)
    a2 = ttk.Frame(adv)
    a2.pack(fill='x', pady=(4, 0))
    ttk.Label(a2, text='舞台顏色：').pack(side='left')
    for v in ('standard', 'pale'):
        ttk.Radiobutton(a2, text=STAGE_NAMES[v], value=v, variable=stage, command=on_stage).pack(side='left')
    ttk.Label(a2, text='　表格排序：').pack(side='left')
    for t, v in (('拍攝時間', 'time'), ('檔名', 'name'), ('顏色', 'color'), ('人物', 'person'), ('星等', 'stars')):
        ttk.Radiobutton(a2, text=t, value=v, variable=sort_by, command=on_option).pack(side='left')
    ttk.Checkbutton(a2, text='依段落分組（照拍攝時間排序時）', variable=group_scene,
                    command=on_option).pack(side='left', padx=10)
    a3 = ttk.Frame(adv)
    a3.pack(fill='x', pady=(4, 0))
    ttk.Label(a3, text='燈光段落：').pack(side='left')
    for t, v in (('自動', 'auto'), ('手動', 'manual'), ('自動＋手動', 'both')):
        ttk.Radiobutton(a3, text=t, value=v, variable=scene_mode, command=on_scene).pack(side='left')
    ttk.Label(a3, text='　從這些檔名號碼開始新段落：').pack(side='left')
    e_split = ttk.Entry(a3, textvariable=splits_text, width=32)
    e_split.pack(side='left')
    e_split.bind('<Return>', lambda e: on_scene())
    ttk.Button(a3, text='套用', command=on_scene).pack(side='left', padx=4)
    ttk.Label(a3, text='例：2921, 3040, 3074', foreground='#777').pack(side='left', padx=6)
    a4 = ttk.Frame(adv)
    a4.pack(fill='x', pady=(4, 0))
    ttk.Label(a4, text='挑圖功能：').pack(side='left')
    for k in FEATURES:
        ttk.Checkbutton(a4, text=FEATURE_NAMES[k], variable=feat[k],
                        command=lambda k=k: on_feature(k)).pack(side='left', padx=(0, 8))
    ttk.Label(a4, text='（不需要的可以關掉；關掉人物分組分析會快很多）', foreground='#777').pack(side='left')

    # 圖例：用色塊代替文字
    legend = ttk.Frame(root, padding=(8, 4))
    legend.pack(fill='x')
    ttk.Label(legend, text='顏色：', foreground='#555').pack(side='left')
    for i in list(range(8)) + [WHITE, DARK]:
        tk.Label(legend, text=' %s ' % tag(i), bg=SWATCH_COLORS[i], fg='#ffffff' if i in (5, 6, DARK) else '#111111',
                 bd=0, padx=1).pack(side='left', padx=1)
    ttk.Label(legend, foreground='#555',
              text='　左邊小方塊：左半＝膚色、右半＝整體　｜　★ 代表張：每段先修這張　｜　其他說明在選單「說明」').pack(side='left')

    def toggle_adv(flip=False):
        if flip:
            adv_open.set(not adv_open.get())
        if adv_open.get():
            adv.pack(fill='x', padx=8, pady=(4, 0), before=legend)
            b_adv.configure(text='進階設定 ▾')
        else:
            adv.pack_forget()
            b_adv.configure(text='進階設定 ▸')

    def show_help():
        messagebox.showinfo('欄位與顏色說明',
                            '顏色：0白(白光/自然膚色) 1紅 2橙 3黃 4綠 5青 6藍 7紫 8粉 9暗 無(沒偵測到臉)\n'
                            '改檔名例：6藍7紫_原檔名 → 前面是優先項目，後面是另一項\n\n'
                            '段落：照拍攝時間切開的同燈光區段；進階設定可以手動輸入檔名號碼分段\n'
                            '代表 ★：每段最適合先修的一張\n'
                            '每列左邊的小方塊：左半是膚色、右半是整體主色\n'
                            '燈光時間軸（表格上方）：點一下就跳到那一段\n'
                            '星等：整批相對初篩（1 星 = 沒有臉、太暗或可能模糊）\n'
                            '人物：同一人歸同一組（P1 照片最多），只比對臉像不像，不辨識是誰\n\n'
                            '「顯示 → 顯示所有欄位」還有：\n'
                            '清晰度：整批相對分數 0~100\n'
                            '亮度：和同一人最亮的照片比\n'
                            '調色起點：臉的色偏方向（色溫＋往暖、色調＋往洋紅），只是建議，不會寫入檔案\n'
                            '整體後的 ?：主色票數偏低，建議人工確認\n'
                            '燈光爆點：很亮又沒顏色的部分（不參與投票）佔亮處的比例\n'
                            '時間後的 *：沒有拍攝時間，改用檔案時間')

    btns = ttk.Frame(root, padding=8)
    btns.pack(fill='x')
    b_analyze = ttk.Button(btns, text='① 分析（預覽，不動檔案）', command=lambda: start_analysis())
    b_apply = ttk.Button(btns, text='② 執行改名', command=lambda: do_apply())
    b_undo = ttk.Button(btns, text='↶ 復原上一次', command=lambda: do_undo())
    b_report = ttk.Button(btns, text='▤ 分析報告', command=lambda: do_report())
    for b in (b_analyze, b_apply, b_undo, b_report):
        b.pack(side='left', padx=4)
    pbar = ttk.Progressbar(btns, length=250)
    pbar.pack(side='right')

    # --- 預覽表格：預設只顯示挑圖最常用的欄位
    cols = ('file', 'time', 'scene', 'rep', 'stars', 'sharp', 'person', 'bright', 'wb', 'faces', 'skin', 'skin_r',
            'main', 'main_r', 'top', 'hl', 'new')
    heads = ('原檔名', '拍攝時間', '段落', '代表', '星等', '清晰度', '人物', '亮度', '調色起點', '臉數', '膚色', '膚色比例',
             '整體', '整體比例', '整體組成', '燈光爆點', '結果')
    widths = (170, 90, 45, 40, 50, 55, 45, 40, 120, 40, 45, 65, 50, 65, 160, 65, 300)
    basic_cols = ('file', 'time', 'scene', 'rep', 'stars', 'person', 'skin', 'main', 'new')
    feat_cols = {'rep': 'rep', 'stars': 'stars', 'person': 'person', 'bright': 'bright', 'wb': 'wb'}

    # 燈光時間軸色帶：整場的整體主色與膚色，點一下跳到那一段
    tl_frame = ttk.Frame(root, padding=(8, 0, 8, 4))
    tl = tk.Canvas(tl_frame, height=62, background='white', highlightthickness=1, highlightbackground='#c8c8c8',
                   cursor='hand2')
    tl.pack(fill='x')

    frame = ttk.Frame(root)
    frame.pack(fill='both', expand=True, padx=8)
    tree = ttk.Treeview(frame, columns=cols, show='tree headings', displaycolumns=basic_cols)
    tree.heading('#0', text='')
    tree.column('#0', width=70, stretch=False, anchor='w')
    for c, hd, w in zip(cols, heads, widths):
        tree.heading(c, text=hd)
        tree.column(c, width=w, anchor='w')
    tree.tag_configure('scenehdr', background='#e6ebf2', font=('Microsoft JhengHei UI', 10, 'bold'))
    sb = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    sbx = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=sb.set, xscrollcommand=sbx.set)
    tree.grid(row=0, column=0, sticky='nsew')
    sb.grid(row=0, column=1, sticky='ns')
    sbx.grid(row=1, column=0, sticky='ew')
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    for i, c in enumerate(TAG_COLORS):
        tree.tag_configure('c%d' % i, background=c)
    tree.tag_configure('err', background='#ffdddd', foreground='#a00')

    def apply_columns():
        base = cols if show_all.get() else basic_cols
        hide = {feat_cols[k] for k in feat_cols if not feat[k].get()}
        if group_scene.get() and sort_by.get() == 'time':
            hide.add('scene')  # 已經依段落分組，不必再顯示段落欄
        tree.configure(displaycolumns=[c for c in base if c not in hide])

    def swatch(skin, main):
        """每列左邊的小方塊：左半膚色、右半整體主色"""
        key = (skin, main)
        if key not in state['swatch']:
            img = tk.PhotoImage(width=28, height=14)
            img.put('#888888', to=(0, 0, 28, 14))
            img.put(SWATCH_COLORS[skin], to=(1, 1, 14, 13))
            img.put(SWATCH_COLORS[main], to=(14, 1, 27, 13))
            state['swatch'][key] = img
        return state['swatch'][key]

    def draw_timeline(rows=None):
        tl.delete('all')
        if rows is not None:
            state['tl'] = sorted([r for r in rows if not r.get('error')], key=lambda r: (r['time'], r['dir'], r['stem']))
        rs = state['tl'] or []
        if not rs or not feat['timeline'].get():
            tl_frame.pack_forget()
            return
        if not tl_frame.winfo_ismapped():
            tl_frame.pack(fill='x', before=frame)
        W = max(tl.winfo_width(), 400)
        L, R = 44, 10
        t0, t1 = rs[0]['time'], rs[-1]['time']
        span = (t1 - t0).total_seconds()
        if span < 1:
            xs = [L + (W - L - R) * i / max(len(rs) - 1, 1) for i in range(len(rs))]
        else:
            xs = [L + (W - L - R) * (r['time'] - t0).total_seconds() / span for r in rs]
        state['tl_x'] = xs
        tl.create_text(4, 12, text='整體', anchor='w', font=('Microsoft JhengHei UI', 8), fill='#555')
        tl.create_text(4, 30, text='膚色', anchor='w', font=('Microsoft JhengHei UI', 8), fill='#555')
        last = -100
        for i, r in enumerate(rs):
            x0 = xs[i]
            x1 = max(xs[i + 1] if i + 1 < len(rs) else x0 + 3, x0 + 2)
            tl.create_rectangle(x0, 4, x1, 20, fill=SWATCH_COLORS[r['main']], outline='')
            tl.create_rectangle(x0, 22, x1, 38, fill=SWATCH_COLORS[r['skin']], outline='')
            if not i or r['scene'] != rs[i - 1]['scene']:
                if i:
                    tl.create_line(x0, 2, x0, 42, fill='#222', dash=(2, 2))
                if x0 - last >= 26:
                    tl.create_text(x0 + 2, 52, text='S%02d' % r['scene'], anchor='w',
                                   font=('Segoe UI', 7), fill='#333')
                    last = x0
            if r.get('rep') and feat['rep'].get():
                tl.create_text(x0, 46, text='★', fill='#b8860b', font=('Segoe UI', 8))

    def on_timeline_click(event):
        rs = state['tl'] or []
        xs = state.get('tl_x') or []
        if not rs or not xs:
            return
        i = min(range(len(xs)), key=lambda k: abs(xs[k] - event.x))
        s = rs[i]['scene']
        target = 'scene-%d' % s if tree.exists('scene-%d' % s) else None
        if target is None:
            target = next((iid for iid in tree.get_children() if tree.set(iid, 'file') == rs[i]['source']), None)
        if target:
            tree.selection_set(target)
            tree.see(target)
            status.set('段落 S%02d（%s 起）' % (s, rs[i]['time'].strftime('%H:%M:%S')))

    tl.bind('<Button-1>', on_timeline_click)
    tl.bind('<Configure>', lambda e: draw_timeline())

    ttk.Label(root, textvariable=status, padding=8).pack(fill='x')

    def set_busy(b):
        state['busy'] = b
        for w in (b_analyze, b_apply, b_undo, b_report):
            w.state(['disabled'] if b else ['!disabled'])
        for i in range(m_tools.index('end') + 1):
            if m_tools.type(i) == 'command':
                m_tools.entryconfig(i, state='disabled' if b else 'normal')
        if not b and output.get() == 'folder':
            m_tools.entryconfig(STRIP_LABEL, state='disabled')

    def current_rows():
        """套用目前選項後的結果（含挑圖資訊），依表格排序方式排好"""
        rows = batch_features(state['results'], mode.get(), order.get(), performer.get(),
                              scene_mode.get(), parse_splits(splits_text.get()))
        sk = slot_order(mode.get(), order.get())
        if sort_by.get() == 'name':
            rows.sort(key=lambda r: (r['dir'], r['stem']))
        elif sort_by.get() == 'person':
            rows.sort(key=lambda r: (1, '', r['source']) if r.get('error') else
                      (0 if r.get('person') else 1, int((r.get('person') or 'P0')[1:]), r['time']))
        elif sort_by.get() == 'stars':
            rows.sort(key=lambda r: (1, 0, r['source']) if r.get('error') else (0, -r['stars'], r['time']))
        elif sort_by.get() == 'color':
            rows.sort(key=lambda r: (1, r['source']) if r.get('error') else
                      (0, build_prefix(r, mode.get(), order.get(), True, time_seq.get()), r['time']))
        return rows, sk[0]

    def refresh_table():
        tree.delete(*tree.get_children())
        rows, sort_key = current_rows()
        f = features_now()
        grouped = group_scene.get() and sort_by.get() == 'time'
        parents = {}
        if grouped:  # 每段一個標題列：張數、時間、主色、代表張
            by = {}
            for r in rows:
                if not r.get('error'):
                    by.setdefault(r['scene'], []).append(r)
            for s, members in by.items():
                cnt = {}
                for r in members:
                    cnt[r['main']] = cnt.get(r['main'], 0) + 1
                dom = max(cnt, key=cnt.get)
                rep_name = next((r['source'] for r in members if r['rep']), '')
                vals = {c: '' for c in cols}
                vals['file'] = '%d 張　主色 %s' % (len(members), label(dom))
                vals['time'] = members[0]['time'].strftime('%H:%M:%S')
                vals['new'] = '到 %s 為止%s' % (members[-1]['time'].strftime('%H:%M:%S'),
                                                ('　｜　★ 先修：' + rep_name) if rep_name and f['rep'] else '')
                parents[s] = tree.insert('', 'end', iid='scene-%d' % s, text='S%02d' % s, open=True,
                                         values=[vals[c] for c in cols], tags=('scenehdr',))
        for r in rows:
            if r.get('error'):
                tree.insert('', 'end', text='⚠', values=(r['source'],) + ('',) * 9 + ('錯誤', '', '', '', r['error'], '', ''),
                            tags=('err',))
                continue
            clean = strip_prefix(r['source'])
            if output.get() == 'folder':
                new = os.path.join(build_subdir(r, mode.get(), order.get(), digits.get()), clean)
            else:
                new = build_prefix(r, mode.get(), order.get(), digits.get(), time_seq.get()) + clean
            extra = len(r['files']) - 1
            if extra:
                new += '  (+%d 個同名檔)' % extra
            top3 = ' '.join('%s%d%%' % (label(i), p * 100) for i, p in r['top'])
            t = r['time'].strftime('%H:%M:%S') + ('' if r['time_src'] == 'EXIF' else '*')
            tree.insert(parents.get(r['scene'], '') if grouped else '', 'end', tags=('c%d' % r[sort_key],),
                        image=swatch(r['skin'], r['main']), values=(
                r['source'], t, 'S%02d' % r['scene'], '★' if r['rep'] and f['rep'] else '',
                '★' * r['stars'] if f['stars'] else '', r['sharp_score'],
                (r.get('person') or '') if f['person'] else '', (r.get('bright') or '') if f['bright'] else '',
                wb_text(r) if f['wb'] else '', r['faces'], label(r['skin']),
                '%d%%' % (r['skin_ratio'] * 100) if r['skin'] != NOFACE else '',
                label(r['main']) + ('?' if r['uncertain'] else ''), '%d%%' % (r['main_ratio'] * 100), top3,
                '%d%%' % (r.get('highlight', 0) * 100), new))
        draw_timeline(rows)

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
        status.set('分析中… 共 %d 張%s' % (len(groups), '（淡色舞台設定）' if stage.get() == 'pale' else ''))

        person_on = feat['person'].get()
        state['person_done'] = person_on

        def worker():
            try:
                res = run_analysis(groups, progress=lambda i, n: q.put(('progress', i, n)), stage=stage.get(),
                                   person=person_on)
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
                    _, notes = build_report(current_rows()[0], mode.get(), order.get(), performer.get(), features_now())
                    warn = [x for x in notes if x.startswith('⚠')]
                    status.set('分析完成：%d 張%s。%s' % (
                        len(msg[1]), '，%d 張讀取失敗' % errs if errs else '',
                        '有 %d 項需要注意，請按「分析報告」查看。' % len(warn) if warn
                        else '可切換上方選項看結果，確認後按「②」。'))
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
        rows, _ = current_rows()  # 已套用「偏重演出者」並算好拍攝時間序號
        plan = plan_renames(rows, mode.get(), order.get(), digits.get(), output.get(), time_seq.get())
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
            export_csv(rows, path, mode.get(), order.get(), digits.get(), output.get(), time_seq.get(), features_now())
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

    def do_report():
        if not state['results']:
            messagebox.showinfo('提示', '請先按「① 分析」')
            return
        rows, _ = current_rows()
        text = report_text(rows, mode.get(), order.get(), folder.get().strip(), performer.get(), features_now())
        win = tk.Toplevel(root)
        win.title('分析報告')
        win.geometry('720x520')
        box = tk.Text(win, wrap='word', font=('Microsoft JhengHei UI', 11), padx=12, pady=10, spacing1=2, spacing3=2)
        box.insert('1.0', text)
        # 提醒依輕重上色：⚠ 需要注意（橘）、ℹ 參考（藍）、✓ 正常（綠）
        box.tag_configure('head', font=('Microsoft JhengHei UI', 13, 'bold'))
        box.tag_configure('sec', font=('Microsoft JhengHei UI', 11, 'bold'))
        box.tag_configure('warn', background='#fff1d6', foreground='#7a4b00', lmargin1=6, lmargin2=22)
        box.tag_configure('info', background='#e7f0fc', foreground='#1d4a8a', lmargin1=6, lmargin2=22)
        box.tag_configure('ok', background='#e3f5e9', foreground='#17663a', lmargin1=6)
        for i, ln in enumerate(text.split('\n'), 1):
            tag_name = ('head' if i == 1 else 'sec' if ln.startswith('需要注意') else 'warn' if ln.startswith('⚠')
                        else 'info' if ln.startswith('ℹ') else 'ok' if ln.startswith('✓') else None)
            if tag_name:
                box.tag_add(tag_name, '%d.0' % i, '%d.end' % i)
        box.configure(state='disabled')
        box.pack(fill='both', expand=True)
        bar = ttk.Frame(win, padding=6)
        bar.pack(fill='x')

        def save():
            f = folder.get().strip()
            if not f or not os.path.isdir(f):
                return
            stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            path, k = os.path.join(f, '_分析報告_%s.txt' % stamp), 1
            while os.path.exists(path):
                k += 1
                path = os.path.join(f, '_分析報告_%s_%d.txt' % (stamp, k))
            with open(path, 'w', encoding='utf-8-sig') as fp:
                fp.write(text)
            messagebox.showinfo('完成', '已存到資料夾內：\n%s' % os.path.basename(path), parent=win)
        ttk.Button(bar, text='存成文字檔', command=save).pack(side='right')
        ttk.Button(bar, text='關閉', command=win.destroy).pack(side='right', padx=6)

    def do_timeline():
        if not state['results']:
            messagebox.showinfo('提示', '請先按「① 分析」')
            return
        rows = [r for r in batch_features(state['results'], mode.get(), order.get(), performer.get())
                if not r.get('error')]
        if not rows:
            return
        win = tk.Toplevel(root)
        win.title('燈光時間軸')
        W, H, L, R = 1000, 260, 70, 20
        cv = tk.Canvas(win, width=W, height=H, background='white')
        cv.pack(fill='both', expand=True)
        t0, t1 = rows[0]['time'], rows[-1]['time']
        span = max((t1 - t0).total_seconds(), 1.0)
        # 照片太少或時間都一樣時，改成照順序平均排開
        use_index = (t1 - t0).total_seconds() < 1
        xs = [L + (W - L - R) * ((i / max(len(rows) - 1, 1)) if use_index else
                                 (r['time'] - t0).total_seconds() / span) for i, r in enumerate(rows)]
        cv.create_text(8, 70, text='整體主色', anchor='w')
        cv.create_text(8, 130, text='膚色', anchor='w')
        cv.create_text(8, 180, text='照片', anchor='w')
        for i, r in enumerate(rows):
            x0 = xs[i]
            x1 = xs[i + 1] if i + 1 < len(rows) else x0 + 4
            x1 = max(x1, x0 + 2)
            cv.create_rectangle(x0, 50, x1, 90, fill=TAG_COLORS[r['main']], outline='')
            cv.create_rectangle(x0, 110, x1, 150, fill=TAG_COLORS[r['skin']], outline='')
            cv.create_line(x0, 172, x0, 188, fill='#333')
            if r['rep']:
                cv.create_text(x0, 200, text='★', fill='#b8860b')
            if i and r['scene'] != rows[i - 1]['scene']:
                cv.create_line(x0, 40, x0, 160, fill='#444', dash=(3, 3))
        last_x = -100
        for s in sorted({r['scene'] for r in rows}):
            first = next(i for i, r in enumerate(rows) if r['scene'] == s)
            if xs[first] - last_x >= 28:  # 段落太近時不畫標籤，避免文字疊在一起
                cv.create_text(xs[first] + 2, 30, text='S%02d' % s, anchor='w', font=('Segoe UI', 8))
                last_x = xs[first]
        cv.create_text(L, H - 20, anchor='w', text=t0.strftime('%H:%M:%S'))
        cv.create_text(W - R, H - 20, anchor='e', text=t1.strftime('%H:%M:%S'))
        cv.create_text(W / 2, H - 20, text='虛線 = 段落交界　★ = 代表張' + ('　（沒有拍攝時間，照順序排列）' if use_index else ''))

    def do_restore():
        f = check_folder()
        if not f:
            return
        extra = []
        if messagebox.askyesno('還原修圖後檔名',
                               '把修圖輸出的照片改回原本的檔名，例如\n'
                               '8粉_0012_DSC02921-Enhanced-NR.jpg → DSC02921-Enhanced-NR.jpg\n\n'
                               '輸出的照片和原始照片放在不同資料夾嗎？\n'
                               '選「是」會再請你選原始照片的資料夾（裡面有改名紀錄，比對最準確）。'):
            d = filedialog.askdirectory(title='選擇原始照片所在的資料夾')
            if d:
                extra.append(d)
        plan, by_log = plan_restore(f, extra, recursive.get())
        if not plan:
            messagebox.showinfo('提示', '沒有找到需要還原的檔名')
            return
        sample = '\n'.join('%s → %s' % (os.path.basename(a), os.path.basename(b)) for a, b in plan[:3])
        how = '（%d 個依改名紀錄比對，%d 個依顏色前綴規則）' % (by_log, len(plan) - by_log)
        if not messagebox.askyesno('確認', '要還原 %d 個檔案的檔名嗎？%s\n\n%s%s\n\n之後可以按「復原上一次」改回來。'
                                   % (len(plan), how, sample, '\n…' if len(plan) > 3 else '')):
            return
        done, errors, log = apply_renames(plan, f)
        state['results'] = []
        refresh_table()
        status.set('已還原 %d 個檔案的檔名' % len(done))
        msg = '已還原 %d 個檔案的檔名。' % len(done)
        if errors:
            msg += '\n\n%d 個失敗：\n' % len(errors) + '\n'.join('%s：%s' % (os.path.basename(a), b) for a, b in errors[:10])
        messagebox.showinfo('完成', msg)

    def on_close():
        remember()
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', on_close)
    toggle_adv()
    on_option()

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
    ap.add_argument('--time-seq', action='store_true', help='同色內依拍攝時間排列（檔名加時間序號）')
    ap.add_argument('--stage', choices=list(STAGE_PRESETS), default='standard',
                    help='舞台顏色：standard 標準、pale 淡色舞台（顏色很淡時用，白光場景容易被判成有色）')
    ap.add_argument('--scenes', choices=['auto', 'manual', 'both'], default='auto',
                    help='燈光段落：auto 自動、manual 只依 --splits、both 兩者都切')
    ap.add_argument('--splits', default='', metavar='號碼', help='從這些檔名號碼開始新段落，例如 "2921,3040,3074"')
    ap.add_argument('--report', nargs='?', const='-', metavar='PATH',
                    help='印出分析報告；給檔名則另外存成文字檔')
    ap.add_argument('--restore', action='store_true', help='還原修圖輸出後的檔名（移除本工具加的前綴）')
    ap.add_argument('--log-folder', action='append', default=[], metavar='DIR',
                    help='搭配 --restore：原始照片所在的資料夾（讀它的改名紀錄），可指定多次')
    a = ap.parse_args(argv)

    if not os.path.isdir(a.folder):
        print('找不到資料夾：%s' % a.folder)
        sys.exit(2)
    if a.restore:
        plan, by_log = plan_restore(a.folder, a.log_folder, a.recursive)
        print('找到 %d 個要還原的檔名（%d 個依改名紀錄，%d 個依前綴規則）' % (len(plan), by_log, len(plan) - by_log))
        for old, new in plan:
            print('  %s -> %s' % (os.path.basename(old), os.path.basename(new)))
        if a.apply:
            done, errors, log = apply_renames(plan, a.folder)
            print('已還原 %d 個，失敗 %d 個，紀錄：%s' % (len(done), len(errors), log))
        else:
            print('（預覽模式，加上 --apply 才會執行）')
        return
    groups = collect_groups(a.folder, a.recursive)
    print('共 %d 張，分析中…' % len(groups))
    results = run_analysis(groups, progress=lambda i, n: print('\r%d/%d' % (i, n), end='', flush=True), stage=a.stage)
    print()
    splits = parse_splits(a.splits)
    rows = batch_features(results, a.mode, a.order, a.performer, a.scenes, splits)
    if splits and a.scenes != 'auto':
        ok = [r for r in rows if not r.get('error')]
        missing = match_splits(ok, splits)[1]
        if missing:
            print('找不到這些分段號碼：%s' % '、'.join(map(str, missing)))
    for r in rows:
        if r.get('error'):
            print('[錯誤] %s：%s' % (r['source'], r['error']))
        else:
            print('%-40s %s S%02d%s %-3s 清晰:%3d %-3s %s 臉:%d 膚色:%s(%d%%) 整體:%s%s(%d%%) 爆點:%d%% %s' % (
                r['source'], r['time'].strftime('%H:%M:%S') + ('' if r['time_src'] == 'EXIF' else '*'),
                r['scene'], '★' if r['rep'] else ' ', '*' * r['stars'], r['sharp_score'], r.get('person') or '-',
                r.get('bright') or '-', r['faces'], label(r['skin']), r['skin_ratio'] * 100, label(r['main']),
                '?' if r['uncertain'] else '', r['main_ratio'] * 100, r.get('highlight', 0) * 100, wb_text(r)))
    if a.report:
        text = report_text(rows, a.mode, a.order, a.folder, a.performer)
        print('\n' + text)
        if a.report != '-':
            with open(a.report, 'w', encoding='utf-8-sig') as fp:
                fp.write(text)
            print('已存分析報告：%s' % a.report)
    if a.csv:
        export_csv(rows, a.csv, a.mode, a.order, not a.no_digits, a.output, a.time_seq)
        print('已匯出 CSV：%s' % a.csv)
    plan = plan_renames(rows, a.mode, a.order, not a.no_digits, a.output, a.time_seq)
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
