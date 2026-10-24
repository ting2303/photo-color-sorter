# -*- coding: utf-8 -*-
"""自動測試：用程式產生的純色圖片，不需要真實照片。執行：python -m unittest discover tests"""
import os
import csv
import sys
import shutil
import tempfile
import unittest

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import photo_color_sorter as pcs  # noqa: E402


def solid(bgr, size=(300, 400)):
    img = np.zeros(size + (3,), np.uint8)
    img[:] = bgr
    return img


def save(path, img):
    ok, buf = cv2.imencode('.jpg', img)
    buf.tofile(path)


class ColorTests(unittest.TestCase):
    def test_overall_colors(self):
        cases = {(0, 0, 255): '紅', (255, 0, 0): '藍', (0, 255, 0): '綠',
                 (0, 140, 255): '橙', (230, 230, 230): '白', (5, 5, 5): '暗'}
        for bgr, name in cases.items():
            key, ratio, _ = pcs.analyze_overall(solid(bgr))
            self.assertEqual(pcs.label(key), name, bgr)

    def test_no_face(self):
        self.assertEqual(pcs.analyze_skin(solid((255, 0, 0)))[0], pcs.NOFACE)

    def test_blown_out_is_white_not_dark(self):
        """幾乎全過曝的照片要判成白光，不能因為爆點被排除就變成「暗」"""
        img = solid((255, 255, 255))
        self.assertEqual(pcs.label(pcs.analyze_overall(img)[0]), '白')
        img[:40, :60] = (255, 80, 0)  # 角落一小塊藍
        self.assertEqual(pcs.label(pcs.analyze_overall(img)[0]), '白')
        img = solid((50, 45, 60))
        img[:210] = 252  # 上面 70% 過曝、下面暗沉舞台
        self.assertEqual(pcs.label(pcs.analyze_overall(img)[0]), '白')
        img = solid((0, 0, 0))
        img[:, :160] = 250  # 黑底加一大片白光
        self.assertEqual(pcs.label(pcs.analyze_overall(img)[0]), '白')

    def test_light_burst_does_not_win(self):
        """偏暗的藍色舞台上，25% 的燈光爆點不能把整張照片拉成白（舊版會判成白）"""
        img = solid((128, 45, 15))
        img[:75] = 250  # 25% 爆點
        key, ratio, top, hl = pcs.analyze_overall(img, return_highlight=True)
        self.assertEqual(pcs.label(key), '藍')
        self.assertAlmostEqual(hl, 0.25, places=2)
        self.assertEqual(pcs.label(top[0][0]), '藍')
        self.assertAlmostEqual(sum(p for _, p in top), 1.0, places=2)  # 比例是同一套票數的佔比

    def test_no_cliff_on_blue_stage(self):
        """爆點比例增加時，藍色舞台不會比舊版更早變成白（舊版約 45% 才變白）"""
        for f in (0.1, 0.2, 0.3, 0.35, 0.4, 0.44):
            img = solid((220, 90, 30))
            img[:int(300 * f)] = 250
            self.assertEqual(pcs.label(pcs.analyze_overall(img)[0]), '藍', f)
        img = solid((220, 90, 30))
        img[:180] = 250  # 爆點佔 60%：大部分是白光，應判白（爆點票數已恢復）
        self.assertEqual(pcs.label(pcs.analyze_overall(img)[0]), '白')

    def test_dim_grey_fallback(self):
        """只有暗沉灰色時：有爆點算白光，沒有爆點算暗"""
        img = solid((70, 70, 70))  # 亮度約 0.27，不算白光
        self.assertEqual(pcs.label(pcs.analyze_overall(img)[0]), '暗')
        img[:30, :40] = 255  # 1% 爆點
        self.assertEqual(pcs.label(pcs.analyze_overall(img)[0]), '白')

    def test_highlight_fraction(self):
        """爆點比例 = 爆點佔亮區的比例，會出現在分析結果裡"""
        img = solid((0, 0, 0))
        img[:, :100] = (255, 80, 0)   # 25% 藍光
        img[:, 100:120] = 255         # 5% 爆點
        key, _, _, hl = pcs.analyze_overall(img, return_highlight=True)
        self.assertEqual(pcs.label(key), '藍')
        self.assertAlmostEqual(hl, 20 / 120, places=2)
        self.assertEqual(len(pcs.analyze_overall(img)), 3)  # 預設回傳格式不變


class RenameTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        save(os.path.join(self.dir, 'A.JPG'), solid((255, 0, 0)))
        open(os.path.join(self.dir, 'A.xmp'), 'w').close()
        open(os.path.join(self.dir, '藍_筆記.txt'), 'w').close()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def analyze(self):
        return [pcs.analyze_group(g) for g in pcs.collect_groups(self.dir)]

    def test_rename_and_undo(self):
        done, errors, log = pcs.apply_renames(pcs.plan_renames(self.analyze()), self.dir)
        self.assertEqual(errors, [])
        self.assertIn('無6藍_A.JPG', os.listdir(self.dir))
        self.assertIn('無6藍_A.xmp', os.listdir(self.dir))       # 同名 XMP 一起改
        self.assertIn('藍_筆記.txt', os.listdir(self.dir))       # 非照片檔不動
        self.assertEqual(pcs.plan_renames(self.analyze()), [])  # 重複執行不疊加
        pcs.undo_log(log)
        self.assertIn('A.JPG', os.listdir(self.dir))

    def test_folder_and_undo(self):
        done, errors, log = pcs.apply_renames(pcs.plan_renames(self.analyze(), output='folder'), self.dir)
        self.assertTrue(os.path.exists(os.path.join(self.dir, '膚色無', '整體6藍', 'A.JPG')))
        self.assertEqual(pcs.collect_groups(self.dir, recursive=True), [])  # 不會再巢狀分類
        pcs.undo_log(log)
        self.assertIn('A.JPG', os.listdir(self.dir))
        self.assertFalse(os.path.exists(os.path.join(self.dir, '膚色無')))  # 空資料夾已清掉

    def test_tampered_log_rejected(self):
        outside = tempfile.NamedTemporaryFile(delete=False)
        outside.close()
        log = os.path.join(self.dir, pcs.LOG_PREFIX + 'x.csv')
        with open(log, 'w', newline='', encoding='utf-8-sig') as fp:
            csv.writer(fp).writerows([['old', 'new'], [os.path.join(self.dir, 'y'), outside.name]])
        with self.assertRaises(PermissionError):
            pcs.undo_log(log)
        self.assertTrue(os.path.exists(outside.name))
        os.remove(outside.name)

    def test_outside_paths_refused(self):
        done, errors, _ = pcs.apply_renames([(os.path.join(self.dir, 'A.JPG'), os.path.join(tempfile.gettempdir(), 'A.JPG'))], self.dir)
        self.assertEqual(done, [])
        self.assertTrue(os.path.exists(os.path.join(self.dir, 'A.JPG')))

    def test_strip_prefix(self):
        self.assertEqual(pcs.strip_prefix('6藍7紫_A.JPG'), 'A.JPG')
        self.assertEqual(pcs.strip_prefix('S06藍_M07紫__A.JPG'), 'A.JPG')
        self.assertEqual(pcs.strip_prefix('藍天白雲_A.JPG'), '藍天白雲_A.JPG')


class ModelTests(unittest.TestCase):
    def test_model_hash(self):
        self.assertTrue(pcs._get_yunet())


if __name__ == '__main__':
    unittest.main()


# ---------------------------------------------------------------- 挑圖輔助


def tiff_exif(dt='2026:06:20 19:30:05', sub='25', big_endian=False):
    """做一段最小的 TIFF/EXIF：IFD0 -> EXIF 子目錄 -> DateTimeOriginal + SubSecTimeOriginal"""
    import struct
    e = '>' if big_endian else '<'
    dtb, subb = dt.encode() + b'\0', sub.encode() + b'\0'
    ifd0_off = 8
    exif_off = ifd0_off + 2 + 12 + 4
    data_off = exif_off + 2 + 2 * 12 + 4
    out = (b'MM' if big_endian else b'II') + struct.pack(e + 'HI', 42, ifd0_off)
    out += struct.pack(e + 'H', 1) + struct.pack(e + 'HHII', 0x8769, 4, 1, exif_off) + struct.pack(e + 'I', 0)
    out += struct.pack(e + 'H', 2)
    out += struct.pack(e + 'HHII', 0x9003, 2, len(dtb), data_off)
    out += struct.pack(e + 'HHI', 0x9291, 2, len(subb)) + subb.ljust(4, b'\0')[:4]
    out += struct.pack(e + 'I', 0) + dtb
    return out


def jpeg_with_exif(img, tiff):
    import struct
    ok, buf = cv2.imencode('.jpg', img)
    jpg = buf.tobytes()
    app1 = b'Exif\0\0' + tiff
    return jpg[:2] + b'\xff\xe1' + struct.pack('>H', len(app1) + 2) + app1 + jpg[2:]


class PickingTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_capture_time_jpeg(self):
        p = os.path.join(self.dir, 'a.jpg')
        with open(p, 'wb') as fp:
            fp.write(jpeg_with_exif(solid((255, 0, 0)), tiff_exif()))
        t = pcs.read_capture_time(p)
        self.assertEqual(t.strftime('%Y-%m-%d %H:%M:%S'), '2026-06-20 19:30:05')
        self.assertEqual(t.microsecond, 250000)  # 小數秒 "25" = 0.25 秒

    def test_capture_time_raw_big_endian(self):
        p = os.path.join(self.dir, 'b.nef')
        with open(p, 'wb') as fp:
            fp.write(tiff_exif('2026:01:02 03:04:05', '7', big_endian=True))
        t = pcs.read_capture_time(p)
        self.assertEqual((t.hour, t.minute, t.second, t.microsecond), (3, 4, 5, 700000))

    def test_capture_time_missing_or_broken(self):
        p = os.path.join(self.dir, 'c.jpg')
        save(p, solid((0, 0, 255)))  # 沒有 EXIF
        self.assertIsNone(pcs.read_capture_time(p))
        for content in (b'', b'\xff\xd8\xff', b'II*\0\xff\xff\xff\xff', os.urandom(5000)):
            with open(p, 'wb') as fp:
                fp.write(content)
            self.assertIsNone(pcs.read_capture_time(p))

    def make_results(self, spec):
        """spec: [(秒數, 整體主色索引, 清晰度, 臉數)] -> 假的分析結果"""
        import datetime
        t0 = datetime.datetime(2026, 6, 20, 19, 0, 0)
        out = []
        for i, (sec, main, sharp, faces) in enumerate(spec):
            out.append(dict(dir=self.dir, stem='P%03d' % i, source='P%03d.jpg' % i, files=['P%03d.jpg' % i],
                            skin=pcs.WHITE, skin_ratio=0.8, faces=faces, main=main, main_ratio=0.6, top=[(main, 0.6)],
                            highlight=0.0, main_perf=main, main_perf_ratio=0.6, top_perf=[(main, 0.6)],
                            sharp=sharp, face_px=100.0 if faces else 0.0, face_bright=0.55 if faces else None,
                            time=t0 + datetime.timedelta(seconds=sec), time_src='EXIF', error=None))
        return out

    def test_scenes_split_on_light_change_and_pause(self):
        BLUE, RED = 5, 0
        spec = [(i * 5, BLUE, 1.0, 1) for i in range(6)]            # 藍 6 張
        spec += [(30 + i * 5, RED, 1.0, 1) for i in range(6)]       # 換紅 6 張
        spec += [(400 + i * 5, RED, 1.0, 1) for i in range(5)]      # 停頓 5 分鐘後還是紅
        rows = pcs.batch_features(self.make_results(spec))
        self.assertEqual([r['scene'] for r in rows], [1] * 6 + [2] * 6 + [3] * 5)

    def test_single_misread_does_not_split(self):
        BLUE, RED = 5, 0
        spec = [(i * 5, BLUE, 1.0, 1) for i in range(9)]
        spec[4] = (20, RED, 1.0, 1)  # 中間一張誤判
        rows = pcs.batch_features(self.make_results(spec))
        self.assertEqual({r['scene'] for r in rows}, {1})

    def test_representative_is_sharpest_face(self):
        spec = [(0, 5, 0.2, 1), (5, 5, 0.9, 1), (10, 5, 2.0, 0), (15, 5, 0.5, 1)]
        rows = pcs.batch_features(self.make_results(spec))
        reps = [r['source'] for r in rows if r['rep']]
        self.assertEqual(reps, ['P001.jpg'])  # 最清楚但沒臉的 P002 不選
        self.assertEqual([r['sharp_score'] for r in rows], [0, 67, 100, 33])

    def test_sorted_by_time_and_errors_kept(self):
        spec = [(50, 5, 1.0, 1), (10, 5, 1.0, 1)]
        res = self.make_results(spec) + [dict(dir=self.dir, stem='bad', source='bad.jpg', files=['bad.jpg'],
                                               error='無法讀取圖片')]
        rows = pcs.batch_features(res)
        self.assertEqual([r['source'] for r in rows], ['P001.jpg', 'P000.jpg', 'bad.jpg'])

    def test_uncertain_flag(self):
        res = self.make_results([(0, 5, 1.0, 1)])
        res[0]['main_ratio'] = 0.3
        self.assertTrue(pcs.batch_features(res)[0]['uncertain'])

    def test_performer_weighting(self):
        """演出者站在小塊藍光裡，背景是大片粉色 LED：偏重演出者時應判藍"""
        img = solid((180, 60, 255))            # 粉色背景佔約 2/3
        img[60:300, 120:280] = (255, 90, 20)   # 演出者身上的藍光，約 1/3
        box = [(180 / 400, 70 / 300, 40 / 400, 27 / 300)]  # 臉框
        self.assertEqual(pcs.label(pcs.analyze_overall(img)[0]), '粉')
        self.assertEqual(pcs.label(pcs.analyze_overall(img, performer_boxes=box)[0]), '藍')

    def test_effective_switches_main(self):
        r = self.make_results([(0, 5, 1.0, 1)])[0]
        r['main_perf'] = 0
        self.assertEqual(pcs.effective(r, True)['main'], 0)
        self.assertEqual(pcs.effective(r, False)['main'], 5)

    def test_analyze_group_and_export(self):
        p = os.path.join(self.dir, 'IMG_1.jpg')
        with open(p, 'wb') as fp:
            fp.write(jpeg_with_exif(solid((255, 0, 0)), tiff_exif()))
        res = [pcs.analyze_group(g) for g in pcs.collect_groups(self.dir)]
        self.assertIsNone(res[0]['error'])
        self.assertEqual(res[0]['time_src'], 'EXIF')
        rows = pcs.batch_features(res)
        out = os.path.join(self.dir, 'out.csv')
        pcs.export_csv(rows, out)
        with open(out, encoding='utf-8-sig') as fp:
            data = list(csv.reader(fp))
        self.assertEqual(data[0][0], '檔名')
        self.assertEqual(data[1][0], 'IMG_1.jpg')
        self.assertEqual(data[1][3], 'S01')
        self.assertTrue(data[1][14].startswith('無6藍_'))
