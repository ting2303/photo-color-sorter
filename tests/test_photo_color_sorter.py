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
        col = {name: i for i, name in enumerate(data[0])}
        self.assertEqual(data[1][col['檔名']], 'IMG_1.jpg')
        self.assertEqual(data[1][col['燈光段落']], 'S01')
        self.assertEqual(data[1][col['星等']], '1')  # 沒有臉
        self.assertTrue(data[1][col['結果']].startswith('無6藍_'))
        self.assertEqual(len(data[1]), len(data[0]))


class StabilityTests(unittest.TestCase):
    """穩定度測試找到的問題"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_elongated_image(self):
        for shape in ((1, 401, 3), (10000, 10, 3), (10, 10000, 3)):
            key, _, _ = pcs.analyze_overall(np.zeros(shape, np.uint8))
            self.assertEqual(pcs.label(key), '暗')
        self.assertEqual(pcs.resize_max(np.zeros((1, 2000, 3), np.uint8), 400).shape[:2], (1, 400))

    def test_hidden_files_ignored(self):
        save(os.path.join(self.dir, 'A.jpg'), solid((255, 0, 0)))
        save(os.path.join(self.dir, '.hidden.jpg'), solid((255, 0, 0)))
        save(os.path.join(self.dir, '._A.jpg'), solid((255, 0, 0)))
        self.assertEqual([g['source'] for g in pcs.collect_groups(self.dir)], ['A.jpg'])
        self.assertEqual([g['source'] for g in pcs.collect_groups(self.dir, recursive=True)], ['A.jpg'])

    def test_repeated_apply_undo_keeps_all_logs(self):
        """改名→復原→改名→復原 在同一秒內完成時，兩份紀錄都要留下，檔案完全復原"""
        save(os.path.join(self.dir, 'A.jpg'), solid((255, 0, 0)))
        for _ in range(2):
            res = [pcs.analyze_group(g) for g in pcs.collect_groups(self.dir)]
            done, errors, log = pcs.apply_renames(pcs.plan_renames(res), self.dir)
            self.assertEqual((len(done), errors), (1, []))
            self.assertEqual(pcs.latest_log(self.dir), log)
            pcs.undo_log(log)
        names = sorted(os.listdir(self.dir))
        self.assertIn('A.jpg', names)
        self.assertEqual(len([n for n in names if '已復原' in n]), 2)
        self.assertIsNone(pcs.latest_log(self.dir))


class TimeSeqAndRestoreTests(unittest.TestCase):
    """同色內依拍攝時間排列、修圖輸出後還原檔名"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, folder, name, color, when=None):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        if when:
            with open(path, 'wb') as fp:
                fp.write(jpeg_with_exif(solid(color), tiff_exif(when, '0')))
        else:
            save(path, solid(color))
        return path

    def test_strip_prefix_with_time_seq(self):
        self.assertEqual(pcs.strip_prefix('8粉_0012_DSC02921.ARW'), 'DSC02921.ARW')
        self.assertEqual(pcs.strip_prefix('8粉6藍_0012_DSC02921-Enhanced-NR.jpg'), 'DSC02921-Enhanced-NR.jpg')
        self.assertEqual(pcs.strip_prefix('粉藍_00012_A.jpg'), 'A.jpg')
        self.assertEqual(pcs.strip_prefix('8粉_12_A.jpg'), '12_A.jpg')  # 兩位數不是時間序號
        self.assertEqual(pcs.strip_prefix('藍天白雲_A.JPG'), '藍天白雲_A.JPG')

    def test_time_seq_orders_by_capture_time_not_number(self):
        """兩台相機：編號大的反而先拍。加時間序號後，同色內依拍攝時間排"""
        self.write(self.dir, 'CAM2_9999.jpg', (255, 0, 0), '2026:06:20 19:00:00')
        self.write(self.dir, 'CAM1_0001.jpg', (255, 0, 0), '2026:06:20 19:00:30')
        self.write(self.dir, 'CAM1_0002.jpg', (0, 0, 255), '2026:06:20 19:01:00')
        res = [pcs.analyze_group(g) for g in pcs.collect_groups(self.dir)]
        rows = pcs.batch_features(res, 'main', 'main')
        plan = pcs.plan_renames(rows, 'main', 'main', True, 'rename', time_seq=True)
        new = sorted(os.path.basename(b) for _, b in plan)
        self.assertEqual(new, ['1紅_0003_CAM1_0002.jpg', '6藍_0001_CAM2_9999.jpg', '6藍_0002_CAM1_0001.jpg'])
        plain = pcs.plan_renames(rows, 'main', 'main', True, 'rename')  # 沒勾選時格式不變
        self.assertIn('6藍_CAM2_9999.jpg', [os.path.basename(b) for _, b in plain])

    def run_tool(self, folder, mode='skin', time_seq=True):
        res = [pcs.analyze_group(g) for g in pcs.collect_groups(folder)]
        rows = pcs.batch_features(res, mode, 'skin')
        done, errors, log = pcs.apply_renames(pcs.plan_renames(rows, mode, 'skin', True, 'rename', time_seq), folder)
        self.assertEqual(errors, [])
        return {os.path.basename(a): os.path.basename(b) for a, b in done}

    def test_restore_exported_jpgs(self):
        """ARW 改名 → 修圖 → 輸出 JPG（後綴不同）→ 還原成原本的檔名"""
        orig, out = os.path.join(self.dir, 'orig'), os.path.join(self.dir, 'export')
        self.write(orig, 'DSC02921.jpg', (255, 0, 0), '2026:06:20 19:00:00')
        self.write(orig, 'DSC02938.jpg', (255, 0, 0), '2026:06:20 19:00:10')
        self.write(orig, 'DSC0293.jpg', (255, 0, 0), '2026:06:20 19:00:20')  # 名字是別人的開頭
        renamed = self.run_tool(orig)
        os.makedirs(out)
        exported = {}
        for o, n in renamed.items():
            stem = os.path.splitext(n)[0]
            for suffix in ('-Enhanced-NR.jpg', '_edit.jpg'):
                self.write(out, stem + suffix, (128, 128, 128))
                exported[stem + suffix] = os.path.splitext(o)[0] + suffix
        plan, by_log = pcs.plan_restore(out, [orig])
        self.assertEqual(by_log, len(exported))
        self.assertEqual({os.path.basename(a): os.path.basename(b) for a, b in plan}, exported)
        # 沒有紀錄時用前綴規則，結果相同
        plan2, by_log2 = pcs.plan_restore(out)
        self.assertEqual(by_log2, 0)
        self.assertEqual({os.path.basename(a): os.path.basename(b) for a, b in plan2}, exported)
        # 執行後可以用「復原上一次」改回來
        done, errors, log = pcs.apply_renames(plan, out)
        self.assertEqual((len(done), errors), (len(exported), []))
        self.assertEqual(sorted(os.listdir(out)), sorted(list(exported.values()) + [os.path.basename(log)]))
        pcs.undo_log(log)
        self.assertEqual(sorted(n for n in os.listdir(out) if not n.startswith('_')), sorted(exported))

    def test_restore_after_running_twice(self):
        """執行兩次（第二次換了分類方式）後輸出的照片，也要還原成最原始的名字"""
        orig = os.path.join(self.dir, 'orig')
        self.write(orig, 'DSC1.jpg', (255, 0, 0), '2026:06:20 19:00:00')
        self.run_tool(orig, mode='skin')
        second = self.run_tool(orig, mode='main')
        stem = os.path.splitext(list(second.values())[0])[0]
        out = os.path.join(self.dir, 'export')
        self.write(out, stem + ' (1).jpg', (0, 0, 0))
        plan, by_log = pcs.plan_restore(out, [orig])
        self.assertEqual([os.path.basename(b) for _, b in plan], ['DSC1 (1).jpg'])
        self.assertEqual(by_log, 1)

    def test_restore_never_overwrites(self):
        out = os.path.join(self.dir, 'export')
        self.write(out, '6藍_0001_DSC1.jpg', (0, 0, 0))
        self.write(out, 'DSC1.jpg', (0, 0, 0))  # 目標名稱已存在
        plan, _ = pcs.plan_restore(out)
        done, errors, _ = pcs.apply_renames(plan, out)
        self.assertEqual((len(done), len(errors)), (0, 1))
        self.assertEqual(sorted(os.listdir(out)), ['6藍_0001_DSC1.jpg', 'DSC1.jpg'])

    def test_restore_with_log_leaves_other_files(self):
        """有改名紀錄時，只還原紀錄裡的照片；自己取名的「白_婚禮.jpg」不能被動到"""
        orig, out = os.path.join(self.dir, 'orig'), os.path.join(self.dir, 'export')
        self.write(orig, 'DSC1.jpg', (255, 0, 0))
        renamed = self.run_tool(orig, time_seq=False)
        self.write(out, os.path.splitext(renamed['DSC1.jpg'])[0] + '-edit.jpg', (0, 0, 0))
        self.write(out, '白_婚禮.jpg', (0, 0, 0))
        plan, by_log = pcs.plan_restore(out, [orig])
        self.assertEqual([os.path.basename(b) for _, b in plan], ['DSC1-edit.jpg'])
        self.assertEqual(by_log, 1)

    def test_restore_longest_match_first(self):
        """紀錄裡有 8粉_DSC_1 和 8粉_DSC_10 時，8粉_DSC_10-edit.jpg 要還原成 DSC_10-edit.jpg"""
        orig, out = os.path.join(self.dir, 'orig'), os.path.join(self.dir, 'export')
        self.write(orig, 'DSC_1.jpg', (255, 0, 0))
        self.write(orig, 'DSC_10.jpg', (255, 0, 0))
        self.run_tool(orig, time_seq=False)
        renamed = sorted(n for n in os.listdir(orig) if not n.startswith('_'))
        for n in renamed:
            self.write(out, os.path.splitext(n)[0] + '-edit.jpg', (0, 0, 0))
        plan, by_log = pcs.plan_restore(out, [orig])
        self.assertEqual(sorted(os.path.basename(b) for _, b in plan), ['DSC_1-edit.jpg', 'DSC_10-edit.jpg'])
        self.assertEqual(by_log, 2)


class FakeRows:
    """產生假分析結果的共用工具（不含測試）"""

    def rows(self, spec):
        """spec: [dict(覆蓋欄位)] -> 假的分析結果（已依時間排序）"""
        import datetime
        t0 = datetime.datetime(2026, 6, 20, 19, 0, 0)
        out = []
        for i, s in enumerate(spec):
            r = dict(dir='.', stem='P%03d' % i, source='P%03d.jpg' % i, files=['P%03d.jpg' % i],
                     skin=pcs.WHITE, skin_ratio=0.8, faces=1, main=5, main_ratio=0.6, top=[(5, 0.6)],
                     highlight=0.0, main_perf=5, main_perf_ratio=0.6, top_perf=[(5, 0.6)],
                     sharp=1.0 + i * 0.01, face_px=100.0, face_bright=0.6, face_emb=None, face_ab=(10.0, 15.0),
                     time=t0 + datetime.timedelta(seconds=5 * i), time_src='EXIF', error=None)
            r.update(s)
            out.append(r)
        return out

    @staticmethod
    def emb(seed):
        rng = np.random.default_rng(seed)
        v = rng.normal(size=128)
        return (v / np.linalg.norm(v)).tolist()


class SixFeatureTests(FakeRows, unittest.TestCase):
    """人物分組、亮度分組、自動評分、調色起點、分析報告"""

    def test_person_groups(self):
        a, b = self.emb(1), self.emb(2)
        near = lambda v, k: (np.array(v) + 0.05 * np.array(self.emb(100 + k))).tolist()
        spec = [dict(face_emb=near(a, i)) for i in range(5)] + [dict(face_emb=near(b, i)) for i in range(3)]
        spec += [dict(face_emb=None, faces=0)]
        rows = pcs.batch_features(self.rows(spec))
        self.assertEqual([r['person'] for r in rows], ['P1'] * 5 + ['P2'] * 3 + [None])

    def test_brightness_groups_per_person(self):
        # 同一人：最亮 0.8；0.8 → 亮，0.55（約 -1.2 級）→ 中，0.3（約 -3 級）→ 暗
        a = self.emb(1)
        spec = [dict(face_emb=a, face_bright=v) for v in (0.8, 0.8, 0.8, 0.55, 0.3)]
        rows = pcs.batch_features(self.rows(spec))
        self.assertEqual([r['bright'] for r in rows], ['亮', '亮', '亮', '中', '暗'])

    def test_stars(self):
        spec = [dict(sharp=0.1), dict(faces=0, face_px=0.0, face_bright=None, face_ab=None)]
        spec += [dict(sharp=5.0 + i, face_px=200.0) for i in range(6)]  # 清楚、臉大
        spec += [dict(sharp=4.8, face_px=50.0)]
        rows = pcs.batch_features(self.rows(spec))
        by = {r['source']: r for r in rows}
        self.assertEqual(by['P000.jpg']['stars'], 1)  # 最模糊
        self.assertEqual((by['P001.jpg']['stars'], by['P001.jpg']['star_why']), (1, '沒有臉'))
        self.assertEqual(by['P007.jpg']['stars'], 3)
        self.assertEqual(by['P008.jpg']['stars'], 2)
        self.assertIn('臉偏小', by['P008.jpg']['star_why'])

    def test_wb_direction(self):
        """自然光的臉 (10, 15)；被藍光打到 b 降 20 → 建議往暖（色溫為正）；洋紅光 a 升 12 → 色調往綠（負）"""
        spec = [dict(), dict(), dict(skin=5, face_ab=(10.0, -5.0)), dict(skin=8, face_ab=(22.0, 15.0)),
                dict(skin=pcs.WHITE, face_ab=(11.0, 16.0))]
        rows = pcs.batch_features(self.rows(spec))
        self.assertEqual(pcs.wb_text(rows[2]), '色溫+20 色調+0')
        self.assertEqual(pcs.wb_text(rows[3]), '色溫+0 色調-12')
        self.assertEqual(pcs.wb_text(rows[4]), '—')  # 差很小

    def test_report_normal_and_warnings(self):
        lines, notes = pcs.build_report(pcs.batch_features(self.rows([dict(main=5)] * 12)))
        self.assertTrue(any(x.startswith('照片：12 張') for x in lines))
        self.assertEqual(notes, ['✓ 沒有發現異常'])
        spec = [dict(main=pcs.WHITE, time_src='檔案時間', faces=0, face_px=0.0, face_bright=None, face_ab=None)] * 12
        bad = [dict(dir='.', stem='x', source='x.jpg', files=['x.jpg'], error='無法讀取圖片')]
        lines, notes = pcs.build_report(pcs.batch_features(self.rows(spec) + bad))
        text = '\n'.join(notes)
        self.assertIn('1 張讀取失敗', text)
        self.assertIn('整體判成白', text)
        self.assertIn('沒偵測到臉', text)
        self.assertIn('沒有讀到任何拍攝時間', text)
        lines, notes = pcs.build_report([])
        self.assertTrue(notes[0].startswith('⚠ 沒有任何照片'))

    def test_sface_model(self):
        self.assertTrue(pcs.sface_available())
        old, pcs._sface = pcs.SFACE_MODEL, None
        try:
            pcs.SFACE_MODEL = os.path.join(tempfile.gettempdir(), 'no_such_model.onnx')
            self.assertFalse(pcs.sface_available())  # 沒有模型時只是略過，不會出錯
            self.assertIsNone(pcs.face_embedding(solid((0, 0, 0)), []))
        finally:
            pcs.SFACE_MODEL, pcs._sface = old, None

    def test_brightness_compares_within_person(self):
        """A 一直站在暗處、B 一直在亮處：各自和自己比，A 不會全被判成暗"""
        a, b = self.emb(1), self.emb(2)
        spec = [dict(face_emb=a, face_bright=0.3) for _ in range(4)] + [dict(face_emb=b, face_bright=0.85) for _ in range(4)]
        rows = pcs.batch_features(self.rows(spec))
        self.assertEqual([r['bright'] for r in rows], ['亮'] * 8)


class ReportFixTests(FakeRows, unittest.TestCase):
    """第二輪穩定度測試找到的問題"""

    def test_all_sharp_batch_has_no_blur_stars(self):
        spec = [dict(sharp=1.0 + 0.003 * i) for i in range(30)]  # 全部清楚、差距很小
        rows = pcs.batch_features(self.rows(spec))
        self.assertFalse([r for r in rows if r['star_why'] == '可能模糊'])

    def test_strong_blur_always_flagged(self):
        spec = [dict(sharp=1.0) for _ in range(5)] + [dict(sharp=0.5)]
        rows = pcs.batch_features(self.rows(spec))
        self.assertEqual(rows[-1]['star_why'], '可能模糊')

    def test_dark_face_reason(self):
        spec = [dict() for _ in range(5)] + [dict(face_bright=0.05, sharp=0.2)]
        rows = pcs.batch_features(self.rows(spec))
        self.assertEqual((rows[-1]['stars'], rows[-1]['star_why']), (1, '臉太暗'))

    def test_grayscale_face_gets_no_wb(self):
        spec = [dict() for _ in range(3)] + [dict(skin=pcs.WHITE, face_ab=(0.5, -0.8))]
        rows = pcs.batch_features(self.rows(spec))
        self.assertEqual(pcs.wb_text(rows[-1]), '')

    def test_report_wb_without_reference(self):
        spec = [dict(skin=5, face_ab=(5.0, -20.0)) for _ in range(12)]  # 全部被藍光照到
        lines, _ = pcs.build_report(pcs.batch_features(self.rows(spec)))
        self.assertTrue(any('沒有在自然光下的臉可當基準' in x for x in lines))

    def test_report_uncertain_advice_depends_on_option(self):
        spec = [dict(main_ratio=0.3) for _ in range(12)]
        _, off = pcs.build_report(pcs.batch_features(self.rows(spec)))
        _, on = pcs.build_report(pcs.batch_features(self.rows(spec)), performer=True)
        self.assertIn('可以勾「整體偏重演出者」', '\n'.join(off))
        self.assertIn('已經勾了「整體偏重演出者」', '\n'.join(on))

    def test_report_no_blur_note_when_no_faces(self):
        spec = [dict(faces=0, face_px=0.0, face_bright=None, face_ab=None) for _ in range(12)]
        _, notes = pcs.build_report(pcs.batch_features(self.rows(spec)))
        text = '\n'.join(notes)
        self.assertIn('沒偵測到臉', text)
        self.assertNotIn('可能模糊', text)

    def test_report_split_person_note(self):
        a = self.emb(1)
        spec = [dict(face_emb=a) for _ in range(8)] + [dict(face_emb=self.emb(10 + i)) for i in range(3)]
        _, notes = pcs.build_report(pcs.batch_features(self.rows(spec)))
        self.assertIn('只有 1～2 張', '\n'.join(notes))

    def test_same_name_different_formats_are_separate(self):
        d = tempfile.mkdtemp()
        try:
            save(os.path.join(d, 'x.jpg'), solid((255, 0, 0)))
            ok, buf = cv2.imencode('.png', solid((0, 0, 255)))
            buf.tofile(os.path.join(d, 'x.png'))
            open(os.path.join(d, 'x.nef'), 'wb').close()
            open(os.path.join(d, 'x.xmp'), 'wb').close()
            groups = pcs.collect_groups(d)
            self.assertEqual(sorted(g['source'] for g in groups), ['x.jpg', 'x.png'])
            self.assertEqual(next(g for g in groups if g['source'] == 'x.jpg')['files'], ['x.jpg', 'x.nef', 'x.xmp'])
            res = [pcs.analyze_group(g) for g in groups]
            self.assertEqual(sorted(pcs.label(r['main']) for r in res), ['紅', '藍'])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_friendly_errors(self):
        d = tempfile.mkdtemp()
        try:
            open(os.path.join(d, 'empty.jpg'), 'wb').close()
            with open(os.path.join(d, 'fake.nef'), 'wb') as fp:
                fp.write(os.urandom(2000))
            for g in pcs.collect_groups(d):
                err = pcs.analyze_group(g)['error']
                self.assertTrue(err.startswith(('無法讀取圖片', '不支援的 RAW 格式', '需要安裝 rawpy')), err)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_dim_face_not_called_blurry(self):
        """臉偏暗（0.12~0.2）時清晰度不可靠：不判模糊，2 星並說明臉太暗"""
        spec = [dict() for _ in range(6)] + [dict(face_bright=0.16, sharp=0.4)]
        rows = pcs.batch_features(self.rows(spec))
        self.assertEqual(rows[-1]['stars'], 2)
        self.assertIn('臉太暗', rows[-1]['star_why'])


class ManualControlTests(FakeRows, unittest.TestCase):
    """手動分段、舞台顏色濃淡"""

    def test_file_number_and_parse(self):
        self.assertEqual(pcs.file_number('DSC02921'), 2921)
        self.assertEqual(pcs.file_number('20260131-DSC05088'), 5088)
        self.assertIsNone(pcs.file_number('cover'))
        self.assertEqual(pcs.parse_splits('3040, 2921  3074，3040'), [2921, 3040, 3074])

    def spec10(self):
        return [dict(stem='DSC%05d' % (100 + i), source='DSC%05d.jpg' % (100 + i)) for i in range(10)]

    def test_manual_splits(self):
        rows = pcs.batch_features(self.rows(self.spec10()), scene_mode='manual', splits=[103, 107])
        self.assertEqual([r['scene'] for r in rows], [1, 1, 1, 2, 2, 2, 2, 3, 3, 3])

    def test_manual_split_nearest_bigger_and_missing(self):
        spec = [s for s in self.spec10() if s['stem'] != 'DSC00105']
        ok = sorted(self.rows(spec), key=lambda r: r['time'])
        idx, missing = pcs.match_splits(ok, [105, 999])
        self.assertEqual([ok[i]['stem'] for i in idx], ['DSC00106'])  # 沒有 105，用最接近的 106
        self.assertEqual(missing, [999])

    def test_both_mode_adds_to_auto(self):
        spec = self.spec10()
        for s in spec[5:]:
            s.update(main=0)  # 後半段換紅光 -> 自動在第 6 張切
        auto = [r['scene'] for r in pcs.batch_features(self.rows(spec))]
        both = [r['scene'] for r in pcs.batch_features(self.rows(spec), scene_mode='both', splits=[102])]
        self.assertEqual(auto, [1] * 5 + [2] * 5)
        self.assertEqual(both, [1, 1, 2, 2, 2, 3, 3, 3, 3, 3])
        self.assertEqual(len([r for r in pcs.batch_features(self.rows(spec), scene_mode='both', splits=[102])
                              if r['rep']]), 3)  # 每段都有代表張

    def test_stage_preset_changes_thresholds(self):
        try:
            pcs.apply_stage_preset('pale')
            self.assertEqual(pcs.NEUTRAL_S, 0.14)
            self.assertEqual(pcs.SKIN_NEUTRAL_S, 0.08)
        finally:
            pcs.apply_stage_preset('standard')
        self.assertEqual(pcs.NEUTRAL_S, 0.25)

    def test_pale_stage_catches_pale_light(self):
        """淡藍色燈光：標準設定判白，淡色舞台設定判藍"""
        d = tempfile.mkdtemp()
        try:
            save(os.path.join(d, 'pale.jpg'), solid((235, 205, 185)))  # 飽和度約 0.21
            g = pcs.collect_groups(d)[0]
            self.assertEqual(pcs.label(pcs.analyze_group(g)['main']), '白')
            self.assertEqual(pcs.label(pcs.analyze_group(g, 'pale')['main']), '藍')
            self.assertEqual(pcs.analyze_group(g, 'pale')['stage'], 'pale')
            self.assertEqual(pcs.NEUTRAL_S, 0.14)
        finally:
            pcs.apply_stage_preset('standard')
            shutil.rmtree(d, ignore_errors=True)

    def test_report_mentions_pale_stage(self):
        spec = [dict(stage='pale', skin=0) for _ in range(10)]
        _, notes = pcs.build_report(pcs.batch_features(self.rows(spec)))
        self.assertIn('建議改回「標準」', '\n'.join(notes))


class FeatureToggleTests(FakeRows, unittest.TestCase):
    """挑圖功能開關、記住設定"""

    def test_settings_roundtrip_and_broken_file(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, 's.json')
            self.assertEqual(pcs.load_settings(path), {})  # 沒有檔案
            self.assertTrue(pcs.save_settings({'mode': 'skin', 'features': {'person': False}}, path))
            self.assertEqual(pcs.load_settings(path)['features'], {'person': False})
            with open(path, 'w') as fp:
                fp.write('{broken')
            self.assertEqual(pcs.load_settings(path), {})  # 壞掉的檔案不會讓程式出錯
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_person_off_skips_embedding(self):
        d = tempfile.mkdtemp()
        try:
            save(os.path.join(d, 'a.jpg'), solid((255, 0, 0)))
            g = pcs.collect_groups(d)[0]
            self.assertIsNone(pcs.analyze_group(g, person=False)['face_emb'])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_report_and_csv_respect_features(self):
        rows = pcs.batch_features(self.rows([dict() for _ in range(12)]))
        off = {'stars': False, 'person': False, 'wb': False}
        lines, _ = pcs.build_report(rows, features=off)
        text = '\n'.join(lines)
        self.assertFalse([x for x in lines if x.startswith(('自動評分', '人物分組', '調色起點'))])
        self.assertIn('已關閉：星等、人物分組、調色起點', text)
        d = tempfile.mkdtemp()
        try:
            out = os.path.join(d, 'o.csv')
            pcs.export_csv(rows, out, features=off)
            with open(out, encoding='utf-8-sig') as fp:
                data = list(csv.reader(fp))
            col = {n: i for i, n in enumerate(data[0])}
            self.assertEqual({data[1][col[k]] for k in ('星等', '評分說明', '人物', '調色起點建議')}, {''})
            self.assertNotEqual(data[1][col['亮度']], '')  # 沒關的照常輸出
        finally:
            shutil.rmtree(d, ignore_errors=True)


class ExtremeInputTests(FakeRows, unittest.TestCase):
    """極端輸入與輸出：細長圖、Excel 公式檔名、寫不了紀錄檔、全黑的臉"""

    def test_degenerate_images_have_no_phantom_faces(self):
        rng = np.random.default_rng(0)
        noise = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        for shape in ((3, 10000, 3), (10, 10000, 3), (9000, 3, 3), (1, 1, 3)):
            img = rng.integers(0, 255, shape, dtype=np.uint8)
            for before in (None, solid((128, 128, 128), (600, 800)), noise):  # 前一張是什麼都不能影響結果
                if before is not None:
                    pcs.analyze_skin(before)
                self.assertEqual(pcs.analyze_skin(img)[2], 0, shape)

    def test_csv_escapes_formula_filenames(self):
        rows = pcs.batch_features(self.rows([dict(source='=1+1.jpg', files=['=1+1.jpg'])]))
        d = tempfile.mkdtemp()
        try:
            out = os.path.join(d, 'o.csv')
            pcs.export_csv(rows, out)
            with open(out, encoding='utf-8-sig') as fp:
                data = list(csv.reader(fp))
            self.assertEqual(data[1][0], "'=1+1.jpg")
            self.assertEqual(pcs._cell('DSC_1.jpg'), 'DSC_1.jpg')
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_no_rename_when_log_cannot_be_written(self):
        import builtins
        from unittest import mock
        d = tempfile.mkdtemp()
        try:
            a = os.path.join(d, 'a.jpg')
            save(a, solid((255, 0, 0)))
            real_open = builtins.open

            def fake_open(path, *args, **kw):
                if pcs.LOG_PREFIX in str(path):
                    raise OSError('No space left on device')
                return real_open(path, *args, **kw)
            with mock.patch('builtins.open', fake_open):
                done, errors, log = pcs.apply_renames([(a, os.path.join(d, '6藍_a.jpg'))], d)
            self.assertEqual((done, log), ([], None))
            self.assertEqual(len(errors), 1)
            self.assertTrue(os.path.exists(a))  # 沒有被改名
            self.assertFalse([f for f in os.listdir(d) if f.startswith(pcs.LOG_PREFIX)])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_empty_plan_leaves_no_log(self):
        d = tempfile.mkdtemp()
        try:
            self.assertEqual(pcs.apply_renames([], d), ([], [], None))
            self.assertEqual(os.listdir(d), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_black_face_counts_as_dark(self):
        rows = pcs.batch_features(self.rows([dict(face_bright=0.6)] * 4 + [dict(face_bright=0.0)]))
        self.assertEqual(rows[-1]['bright'], '暗')

    def test_timeline_compresses_long_gaps(self):
        import datetime
        rows = self.rows([dict() for _ in range(5)])  # 每 5 秒一張
        rows[-1]['time'] = datetime.datetime(2099, 12, 31)  # 相機時間設錯的一張
        xs = pcs.timeline_positions(rows)
        self.assertEqual((xs[0], xs[-1]), (0.0, 1.0))
        self.assertGreater(xs[3], 0.3)  # 其他照片沒有被擠在最左邊
        self.assertEqual(xs, sorted(xs))
        same = self.rows([dict(time=rows[0]['time']) for _ in range(3)])
        self.assertEqual(pcs.timeline_positions(same), [0.0, 0.5, 1.0])
        self.assertEqual(pcs.timeline_positions(rows[:1]), [0.0])

    def test_report_flags_future_capture_time(self):
        import datetime
        rows = self.rows([dict() for _ in range(3)])
        rows[1]['time'] = datetime.datetime(2099, 1, 1)
        _, notes = pcs.build_report(pcs.batch_features(rows))
        self.assertTrue([x for x in notes if x.startswith('ℹ 1 張的拍攝時間在未來')])
