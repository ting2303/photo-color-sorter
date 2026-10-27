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
                     sharp=1.0 + i * 0.01, face_px=100.0, face_bright=0.6, face_ab=(10.0, 15.0),
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
    """亮度分組、自動評分、調色起點、分析報告"""

    def test_no_person_recognition(self):
        """v1.5 起只偵測有沒有人、有幾個人，不辨認是不是同一個人：沒有辨識模型、沒有人物欄位與關鍵字"""
        for name in ('SFACE_MODEL', '_get_sface', 'face_embedding', '_assign_persons', 'SAME_PERSON_COS'):
            self.assertFalse(hasattr(pcs, name), name)
        self.assertNotIn('person', pcs.FEATURES)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertFalse([f for f in os.listdir(root) if 'recognition' in f.lower()])
        rows = pcs.batch_features(self.rows([dict(faces=2), dict(faces=1)]))
        self.assertFalse([r for r in rows if 'person' in r or 'face_emb' in r])
        self.assertFalse([k for k in pcs.xmp_fields(rows[0])['keywords'] if '人物' in k])

    def test_brightness_groups(self):
        # 整批最亮 0.8；0.8 → 亮，0.55（約 -1.2 級）→ 中，0.3（約 -3 級）→ 暗
        spec = [dict(face_bright=v) for v in (0.8, 0.8, 0.8, 0.55, 0.3)]
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

    def test_brightness_compares_with_whole_batch(self):
        """不分人：一半站在暗處（0.3）、一半在亮處（0.85），暗處的和整批最亮的比 → 暗"""
        spec = [dict(face_bright=0.3) for _ in range(4)] + [dict(face_bright=0.85) for _ in range(4)]
        rows = pcs.batch_features(self.rows(spec))
        self.assertEqual([r['bright'] for r in rows], ['暗'] * 4 + ['亮'] * 4)


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
            self.assertTrue(pcs.save_settings({'mode': 'skin', 'features': {'bright': False}}, path))
            self.assertEqual(pcs.load_settings(path)['features'], {'bright': False})
            with open(path, 'w') as fp:
                fp.write('{broken')
            self.assertEqual(pcs.load_settings(path), {})  # 壞掉的檔案不會讓程式出錯
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_analysis_has_no_face_features(self):
        """分析結果只有人數，沒有任何可以拿來比對身分的臉部特徵"""
        d = tempfile.mkdtemp()
        try:
            save(os.path.join(d, 'a.jpg'), solid((255, 0, 0)))
            r = pcs.analyze_group(pcs.collect_groups(d)[0])
            self.assertIn('faces', r)
            self.assertNotIn('face_emb', r)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_report_and_csv_respect_features(self):
        rows = pcs.batch_features(self.rows([dict() for _ in range(12)]))
        off = {'stars': False, 'bright': False, 'wb': False}
        lines, _ = pcs.build_report(rows, features=off)
        text = '\n'.join(lines)
        self.assertFalse([x for x in lines if x.startswith(('自動評分', '亮度分組', '調色起點'))])
        self.assertIn('已關閉：星等、亮度分組、調色起點', text)
        d = tempfile.mkdtemp()
        try:
            out = os.path.join(d, 'o.csv')
            pcs.export_csv(rows, out, features=off)
            with open(out, encoding='utf-8-sig') as fp:
                data = list(csv.reader(fp))
            col = {n: i for i, n in enumerate(data[0])}
            self.assertEqual({data[1][col[k]] for k in ('星等', '評分說明', '亮度', '調色起點建議')}, {''})
            self.assertIn('★', [row[col['代表張']] for row in data[1:]])  # 沒關的照常輸出
            self.assertNotIn('人物', data[0])
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


# ---------------------------------------------------------------- 寫入 Lightroom 標籤（XMP）

LR_XMP = '''<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:lr="http://ns.adobe.com/lightroom/1.0/"
   xmp:Rating="4"
   xmp:Label="Green"
   crs:Version="16.0"
   crs:Exposure2012="+0.35"
   crs:Look="A &amp; B&#xA;第二行&#x9;tab"
   crs:HasSettings="True">
   <crs:ToneCurvePV2012>
    <rdf:Seq>
     <rdf:li>0, 0</rdf:li>
     <rdf:li>255, 255</rdf:li>
    </rdf:Seq>
   </crs:ToneCurvePV2012>
   <crs:LookTable>
    <rdf:Description crs:Name="Adobe Color" crs:Amount="1"/>
   </crs:LookTable>
   <dc:subject>
    <rdf:Bag>
     <rdf:li>婚禮</rdf:li>
     <rdf:li>藍</rdf:li>
    </rdf:Bag>
   </dc:subject>
   <lr:hierarchicalSubject>
    <rdf:Bag>
     <rdf:li>活動|婚禮</rdf:li>
     <rdf:li>色彩|藍</rdf:li>
    </rdf:Bag>
   </lr:hierarchicalSubject>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
'''.encode('utf-8')


def canonical_without_ours(data, ours=()):
    """把本工具會動的欄位（星等、色標、「舞台色彩|…」與 ours 裡的最末層字）拿掉後做 C14N 正規化：
    其他內容（crs 修圖設定、使用者關鍵字）必須完全一樣"""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(data)
    xmp_ns, rdf_ns = '{http://ns.adobe.com/xap/1.0/}', '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}'
    ours = set(ours)
    for el in root.iter():
        for k in (xmp_ns + 'Rating', xmp_ns + 'Label'):
            el.attrib.pop(k, None)
        for bag in el.findall(rdf_ns + 'Bag'):
            for li in list(bag):
                t = (li.text or '').strip()
                if t.startswith(pcs.XMP_ROOT + '|') or t in ours:
                    bag.remove(li)
    for el in root.iter():  # 縮排空白不算內容
        if el.text is not None and not el.text.strip():
            el.text = None
        el.tail = None
    return ET.canonicalize(ET.tostring(root, encoding='unicode'))


class XmpTests(FakeRows, unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def make(self, files_per_photo, specs=None):
        """在暫存資料夾建立檔案，回傳 batch_features 算好的 rows"""
        specs = specs or [dict() for _ in files_per_photo]
        for i, files in enumerate(files_per_photo):
            specs[i] = dict(specs[i], dir=self.dir, stem=os.path.splitext(files[0])[0], source=files[0], files=files)
            for f in files:
                with open(os.path.join(self.dir, f), 'wb') as fp:
                    fp.write(LR_XMP if f.lower().endswith('.xmp') else b'raw-bytes-' + f.encode())
        return pcs.batch_features(self.rows(specs))

    def photo_hashes(self):
        import hashlib
        out = {}
        for f in os.listdir(self.dir):
            if not f.lower().endswith(('.xmp', '.csv')):
                with open(os.path.join(self.dir, f), 'rb') as fp:
                    out[f] = hashlib.sha256(fp.read()).hexdigest()
        return out

    def read(self, name):
        with open(os.path.join(self.dir, name), 'rb') as fp:
            return fp.read()

    def test_new_xmp_for_raw(self):
        rows = self.make([['A.ARW', 'A.JPG']], [dict(skin=7, main=5)])
        before = self.photo_hashes()
        plan, skipped = pcs.plan_xmp(rows)
        self.assertEqual((len(plan), skipped), (1, []))
        self.assertEqual(plan[0]['xmp'], os.path.join(self.dir, 'A.xmp'))
        done, errors, log = pcs.apply_xmp(plan, self.dir)
        self.assertEqual((len(done), errors), (1, []))
        x = pcs.read_xmp(self.read('A.xmp'))
        self.assertEqual(x['rating'], str(rows[0]['stars']))
        self.assertEqual(x['label'], 'Purple')  # 預設依人：臉是粉 → 紫標
        self.assertIn('舞台色彩|代表張', x['hier'])  # 只有一張，一定是代表張
        self.assertIn('舞台色彩|膚色|粉', x['hier'])
        self.assertIn('舞台色彩|整體|藍', x['hier'])
        self.assertIn('舞台色彩|段落|S01', x['hier'])
        self.assertIn('粉', x['subject'])
        self.assertEqual(self.photo_hashes(), before)  # 照片本身完全沒動

    def test_merge_keeps_develop_settings_and_user_values(self):
        rows = self.make([['B.ARW', 'B.xmp']], [dict(skin=7)])
        done, errors, _ = pcs.apply_xmp(pcs.plan_xmp(rows)[0], self.dir)
        self.assertEqual((done[0][1], sorted(done[0][2]), errors), ('merged', ['Label', 'Rating'], []))
        new = self.read('B.xmp')
        x = pcs.read_xmp(new)
        self.assertEqual((x['rating'], x['label']), ('4', 'Green'))  # 使用者原本的星等、色標保留
        self.assertIn('婚禮', x['subject'])
        self.assertIn('活動|婚禮', x['hier'])
        self.assertIn('舞台色彩|膚色|粉', x['hier'])
        added = {h.split('|')[-1] for h in x['hier'] if h.startswith('舞台色彩|')} - set(pcs.read_xmp(LR_XMP)['subject'])
        self.assertEqual(canonical_without_ours(new, added), canonical_without_ours(LR_XMP))  # 其他內容完全一樣
        import xml.etree.ElementTree as ET
        crs = '{http://ns.adobe.com/camera-raw-settings/1.0/}'
        rdf = '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}'
        old_d, new_d = ET.fromstring(LR_XMP).find('.//' + rdf + 'Description'), ET.fromstring(new).find('.//' + rdf + 'Description')
        self.assertEqual({k: v for k, v in old_d.attrib.items() if k.startswith(crs)},
                         {k: v for k, v in new_d.attrib.items() if k.startswith(crs)})
        self.assertEqual(new_d.get(crs + 'Look'), 'A & B\n第二行\ttab')  # 換行、tab 沒被改成空白

    def test_fill_empty_rating_and_zero(self):
        data = LR_XMP.replace(b'xmp:Rating="4"', b'xmp:Rating="0"').replace(b'   xmp:Label="Green"\n', b'')
        new, kept = pcs.merge_xmp(data, {'rating': 3, 'label': 'Red', 'keywords': []})
        x = pcs.read_xmp(new)
        self.assertEqual((x['rating'], x['label'], kept), ('3', 'Red', []))

    def test_rewrite_replaces_old_keywords_only(self):
        first, _ = pcs.merge_xmp(LR_XMP, {'rating': None, 'label': None,
                                          'keywords': ['舞台色彩|膚色|粉', '舞台色彩|整體|藍', '舞台色彩|段落|S01']})
        second, _ = pcs.merge_xmp(first, {'rating': None, 'label': None,
                                          'keywords': ['舞台色彩|膚色|紅', '舞台色彩|整體|藍', '舞台色彩|段落|S02']})
        x = pcs.read_xmp(second)
        ours = [h for h in x['hier'] if h.startswith('舞台色彩|')]
        self.assertEqual(sorted(ours), sorted(['舞台色彩|膚色|紅', '舞台色彩|整體|藍', '舞台色彩|段落|S02']))
        self.assertNotIn('粉', x['subject'])
        self.assertNotIn('S01', x['subject'])
        self.assertIn('藍', x['subject'])  # 使用者自己的「色彩|藍」還在用，不能刪
        self.assertEqual(x['subject'].count('藍'), 1)
        self.assertIn('婚禮', x['subject'])
        self.assertEqual(pcs.merge_xmp(second, {'rating': None, 'label': None,
                                               'keywords': ['舞台色彩|膚色|紅', '舞台色彩|整體|藍', '舞台色彩|段落|S02']})[0],
                         second)  # 結果一樣時內容完全不變（不會每次都重寫）

    def test_second_run_writes_nothing(self):
        """結果一樣時，第二次寫入不會動到任何檔案（新建的 .xmp 也一樣）"""
        rows = self.make([['Q.ARW'], ['R.ARW', 'R.xmp']])
        done, _, _ = pcs.apply_xmp(pcs.plan_xmp(rows)[0], self.dir)
        self.assertEqual(len(done), 2)
        rows = pcs.batch_features(self.rows([dict(r, files=r['files'] + (['Q.xmp'] if r['source'] == 'Q.ARW' else []))
                                             for r in rows]))
        done, errors, log = pcs.apply_xmp(pcs.plan_xmp(rows)[0], self.dir)
        self.assertEqual((done, errors, log), ([], [], None))

    def test_undo_restores_exactly(self):
        rows = self.make([['C.ARW'], ['D.ARW', 'D.xmp']])
        before = {f: self.read(f) for f in os.listdir(self.dir)}
        done, errors, log = pcs.apply_xmp(pcs.plan_xmp(rows)[0], self.dir)
        self.assertEqual(len(done), 2)
        self.assertTrue(os.path.exists(os.path.join(self.dir, 'C.xmp')))
        self.assertEqual(pcs.latest_log(self.dir), log)
        n, errs = pcs.undo_log(log)
        self.assertEqual((n, errs), (2, []))
        after = {f: self.read(f) for f in os.listdir(self.dir) if not f.startswith(pcs.LOG_PREFIX)}
        self.assertEqual(after, before)  # 新建的刪掉、合併的逐位元組還原

    def test_undo_skips_files_changed_later(self):
        rows = self.make([['E.ARW']])
        done, errors, log = pcs.apply_xmp(pcs.plan_xmp(rows)[0], self.dir)
        path = os.path.join(self.dir, 'E.xmp')
        with open(path, 'ab') as fp:
            fp.write(b'<!-- Lightroom changed this -->')
        n, errs = pcs.undo_log(log)
        self.assertEqual((n, len(errs)), (0, 1))
        self.assertTrue(os.path.exists(path))  # 被改過的不刪

    def test_disabled_features_not_written(self):
        rows = self.make([['F.ARW']])
        rows[0]['bright'] = '中'
        on = {'stars': False, 'rep': False, 'bright': False}
        f = pcs.xmp_fields(rows[0], on, label_mode='rep')
        self.assertEqual((f['rating'], f['label']), (None, None))
        self.assertFalse([k for k in f['keywords'] if '|代表張' in k or '|亮度|' in k])
        f = pcs.xmp_fields(rows[0])
        self.assertIn('舞台色彩|代表張', f['keywords'])
        self.assertIn('舞台色彩|亮度|中', f['keywords'])
        new, _ = pcs.merge_xmp(None, pcs.xmp_fields(rows[0], on, label_mode='none'))
        x = pcs.read_xmp(new)
        self.assertEqual((x['rating'], x['label']), ('', ''))

    def test_jpg_png_tiff_dng_not_written(self):
        rows = self.make([['G.JPG'], ['H.png'], ['I.tif'], ['J.DNG'], ['K.NEF']])
        plan, skipped = pcs.plan_xmp(rows)
        self.assertEqual([p['source'] for p in plan], ['K.NEF'])
        self.assertEqual(sorted(s for s, _ in skipped), ['G.JPG', 'H.png', 'I.tif', 'J.DNG'])
        self.assertTrue(pcs.xmp_summary(rows[0]).startswith('（JPG'))

    def test_outside_folder_refused(self):
        other = tempfile.mkdtemp()
        try:
            plan = [{'xmp': os.path.join(other, 'X.xmp'), 'fields': {'rating': 1, 'label': None, 'keywords': []},
                     'source': 'X.ARW'}]
            done, errors, log = pcs.apply_xmp(plan, self.dir)
            self.assertEqual((done, log), ([], None))
            self.assertFalse(os.path.exists(os.path.join(other, 'X.xmp')))
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_nothing_written_when_log_cannot_be_written(self):
        import builtins
        from unittest import mock
        rows = self.make([['L.ARW']])
        real_open = builtins.open

        def fake_open(path, *args, **kw):
            if pcs.LOG_PREFIX in str(path):
                raise OSError('No space left on device')
            return real_open(path, *args, **kw)
        with mock.patch('builtins.open', fake_open):
            done, errors, log = pcs.apply_xmp(pcs.plan_xmp(rows)[0], self.dir)
        self.assertEqual((done, log, len(errors)), ([], None, 1))
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'L.xmp')))

    def test_broken_xmp_left_untouched(self):
        rows = self.make([['M.ARW']])
        with open(os.path.join(self.dir, 'M.xmp'), 'wb') as fp:
            fp.write(b'<x:xmpmeta broken')
        rows[0]['files'] = ['M.ARW', 'M.xmp']
        done, errors, _ = pcs.apply_xmp(pcs.plan_xmp(rows)[0], self.dir)
        self.assertEqual((done, len(errors)), ([], 1))
        self.assertEqual(self.read('M.xmp'), b'<x:xmpmeta broken')

    def test_tampered_xmp_log_rejected(self):
        outside = tempfile.NamedTemporaryFile(suffix='.xmp', delete=False)
        outside.close()
        log = os.path.join(self.dir, pcs.LOG_PREFIX + 'XMP_x.csv')
        with open(log, 'w', newline='', encoding='utf-8-sig') as fp:
            csv.writer(fp).writerows([['action', 'xmp', 'sha_before', 'sha_after', 'original_base64'],
                                      ['created', outside.name, '', pcs._sha(b''), '']])
        with self.assertRaises(PermissionError):
            pcs.undo_log(log)
        self.assertTrue(os.path.exists(outside.name))
        os.remove(outside.name)

    def test_rename_keeps_xmp_paired(self):
        rows = self.make([['N.ARW']], [dict(skin=7, main=5)])
        pcs.apply_xmp(pcs.plan_xmp(rows)[0], self.dir)
        groups = pcs.collect_groups(self.dir)
        self.assertEqual(groups[0]['files'], ['N.ARW', 'N.xmp'])  # 改檔名時 .xmp 會跟著 RAW 一起改

    def test_restore_ignores_xmp_logs(self):
        rows = self.make([['O.ARW']])
        pcs.apply_xmp(pcs.plan_xmp(rows)[0], self.dir)
        self.assertEqual(pcs._log_mappings([self.dir]), {})


# ---------------------------------------------------------------- 人數、準確率評估、標註工具

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import evaluate  # noqa: E402
import label_tool  # noqa: E402


class PeopleCountTests(FakeRows, unittest.TestCase):
    def test_people_text(self):
        self.assertEqual([pcs.people_text(n) for n in (0, 1, 4, 5, 12)], ['0人', '1人', '4人', '5人以上', '5人以上'])

    def test_people_in_xmp_summary_and_report(self):
        rows = pcs.batch_features(self.rows([dict(faces=3, files=['A.ARW'], source='A.ARW'), dict(faces=0), dict(faces=7)]))
        self.assertIn('舞台色彩|人數|3人', pcs.xmp_fields(rows[0])['keywords'])
        self.assertIn('舞台色彩|人數|5人以上', pcs.xmp_fields(rows[2])['keywords'])
        self.assertTrue(pcs.xmp_summary(rows[0]).endswith('3人'))
        lines, _ = pcs.build_report(rows)
        self.assertIn('偵測到的人數：0人 1、3人 1、5人以上 1', lines)


class EvaluateTests(unittest.TestCase):
    def test_key_ignores_prefix_and_extension(self):
        self.assertEqual(evaluate.key_of('8粉6藍_DSC02921.ARW'), 'dsc02921')
        self.assertEqual(evaluate.key_of('S01紅_M01紅__DSC02921.jpg'), 'dsc02921')
        self.assertEqual(evaluate.key_of('DSC02921.JPG'), 'dsc02921')

    def test_halves_split_everything_once(self):
        names = ['DSC%05d.ARW' % i for i in range(200)]
        a = {n for n in names if evaluate.in_half(n, 'A')}
        b = {n for n in names if evaluate.in_half(n, 'B')}
        self.assertEqual(a | b, set(names))
        self.assertFalse(a & b)
        self.assertTrue(60 < len(a) < 140)  # 大致對半

    def test_score(self):
        labels = [{'檔名': 'A.ARW', '膚色': '粉', '整體': '藍', '人數': '2'},
                  {'檔名': 'B.ARW', '膚色': '白', '整體': '藍', '人數': ''},
                  {'檔名': 'C.ARW', '膚色': '', '整體': '紅', '人數': '5'},
                  {'檔名': 'D.ARW', '膚色': '白', '整體': '白', '人數': '1'}]
        preds = {'a': {'檔名': '8粉6藍_A.ARW', '膚色': '粉', '整體': '藍', '人數': 2},
                 'b': {'檔名': 'B.ARW', '膚色': '藍', '整體': '藍', '人數': 1},
                 'c': {'檔名': 'C.ARW', '膚色': '無', '整體': '紅', '人數': 8}}
        s = evaluate.score(labels, preds)
        self.assertEqual(s['n'], 3)
        self.assertEqual(s['missing'], ['D.ARW'])
        self.assertEqual(s['skin'], [1, 2])      # C 的膚色空白不計分
        self.assertEqual(s['main'], [3, 3])
        self.assertEqual(s['people'][:2], [2, 2])  # 標 5 = 5 人以上，程式 8 人算對
        self.assertEqual(s['cm_skin'][('白', '藍')], 1)
        self.assertEqual(s['wrong'][0][1], 'B.ARW')
        text = evaluate.report(['x'], s, 'standard', None, '', '測試')
        self.assertIn('| 膚色 | 50.0%（1/2） |', text)

    def test_bad_label_value_rejected(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, 'labels.csv'), 'w', encoding='utf-8-sig', newline='') as fp:
                fp.write('檔名,膚色,整體\nA.ARW,藍色,藍\n')
            with self.assertRaises(ValueError):
                evaluate.read_labels(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class LabelToolTests(unittest.TestCase):
    def test_roundtrip_and_refuse_other_csv(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 'labels.csv')
            label_tool.write_labels(p, {'A.ARW': {'檔名': 'A.ARW', '膚色': '粉', '整體': '藍', '人數': '2', '備註': ''}})
            self.assertEqual(label_tool.read_labels(p)['A.ARW']['膚色'], '粉')
            with open(p, 'w', encoding='utf-8') as fp:
                fp.write('name,value\n1,2\n')
            with self.assertRaises(ValueError):  # 不是標註檔，不能蓋掉
                label_tool.read_labels(p)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_keys_match_filename_codes(self):
        self.assertEqual(label_tool.KEY_COLORS['6'], '藍')
        self.assertEqual(label_tool.KEY_COLORS['0'], '白')
        self.assertEqual(label_tool.KEY_COLORS['8'], '粉')
        self.assertNotIn('', label_tool.KEY_COLORS)


class ColorLabelTests(FakeRows, unittest.TestCase):
    """Lightroom 色標：依人（膚色）或依背景（整體），對到 Lightroom 的 5 種色標"""

    def test_mapping_covers_every_color(self):
        expect = {'紅': 'Red', '橙': 'Yellow', '黃': 'Yellow', '綠': 'Green', '青': 'Green',
                  '藍': 'Blue', '紫': 'Purple', '粉': 'Purple', '白': None, '暗': None, '無': None}
        for idx in range(len(pcs.CATEGORIES)):
            r = dict(skin=idx, main=pcs.WHITE)
            i = pcs.label_index(r, 'skin')
            self.assertEqual(pcs.LR_LABELS[i] if i is not None else None, expect[pcs.label(idx)], pcs.label(idx))

    def test_person_or_background(self):
        rows = pcs.batch_features(self.rows([dict(skin=7, main=5, files=['A.ARW'], source='A.ARW')]))
        self.assertEqual(pcs.xmp_fields(rows[0], label_mode='skin')['label'], 'Purple')  # 臉粉
        self.assertEqual(pcs.xmp_fields(rows[0], label_mode='main')['label'], 'Blue')    # 背景藍
        self.assertEqual(pcs.xmp_fields(rows[0], label_mode='rep')['label'], 'Red')      # 代表張
        self.assertIsNone(pcs.xmp_fields(rows[0], label_mode='none')['label'])
        self.assertIn('紫標', pcs.xmp_summary(rows[0], label_mode='skin'))
        self.assertIn('藍標', pcs.xmp_summary(rows[0], label_mode='main'))

    def test_custom_label_names(self):
        rows = pcs.batch_features(self.rows([dict(main=5)]))
        names = ['紅色', '黃色', '綠色', '藍色', '紫色']
        self.assertEqual(pcs.xmp_fields(rows[0], label_mode='main', label_names=names)['label'], '藍色')
        self.assertEqual(pcs.clean_label_names(['', 'Y', '', '', '']), ('Red', 'Y', 'Green', 'Blue', 'Purple'))
        self.assertEqual(pcs.clean_label_names(['only', 'two']), pcs.LR_LABELS)  # 數量不對時用預設

    def test_existing_label_still_kept(self):
        data = LR_XMP  # 原本是 Green
        new, kept = pcs.merge_xmp(data, {'rating': None, 'label': 'Blue', 'keywords': []})
        self.assertEqual(pcs.read_xmp(new)['label'], 'Green')
        self.assertIn('Label', kept)
