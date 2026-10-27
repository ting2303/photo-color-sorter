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
