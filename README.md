# 舞台照片色彩分類工具 Photo Color Sorter

自動判斷舞台照片中 **「臉被照成什麼顏色」** 與 **「整張照片的主要顏色」**，一鍵**改檔名**或**分資料夾**。匯入 Lightroom Classic 後用檔名排序，照片就會依燈光顏色排好，修圖更快。

![判斷範例](docs/images/examples.jpg)
<sub>實際判斷結果。框線是偵測到的臉（已打馬賽克保護隱私），下方是「臉的顏色／整體主色」和產生的檔名前綴。</sub>

- ✅ **簡單好用**：下載程式（約 60 MB）、解壓縮、雙擊開啟，不用另外裝 Python（Windows 10／11）
- ✅ **完全離線**：不連網路、不上傳照片
- ✅ **不會弄壞照片**：只改名或搬移，不修改內容、不刪檔，隨時可一鍵復原
- ✅ **支援 RAW**：Canon、Nikon、Sony、Fujifilm 等主流 RAW，RAW + JPG + XMP 同名檔一起處理

📘 **[下載圖文使用教學 PDF](docs/使用教學.pdf)**

⭐ 覺得好用的話，請幫忙按右上角的 **Star**，讓更多攝影師看到！

> 🆓 **個人與非營利使用免費**｜🚫 **禁止商業用途**（詳見[授權](#授權與免責聲明)）

---

## 快速開始

### 方法一：直接下載程式（推薦）
1. 到右側 **[Releases](../../releases/latest)** 下載 `PhotoColorSorter-Windows.zip`
2. 右鍵 →「解壓縮全部」
3. 雙擊 `PhotoColorSorter.exe`
   - 若出現「Windows 已保護您的電腦」→ 點「其他資訊」→「仍要執行」（原因見 [SECURITY.md](SECURITY.md)）

> 💡 也可以直接把照片資料夾**拖到 `PhotoColorSorter.exe` 上**，程式會自動開啟並開始分析。

### 方法二：從原始碼執行（進階）
需要 Python 3.10 以上：
```bash
pip install -r requirements.txt
python photo_color_sorter.py
```

---

## 使用方式

> ⚠️ **請在匯入 Lightroom 之前執行，並先備份原始照片。** 已匯入的照片在外部改名，Lightroom 會找不到檔案。

1. **選擇**照片資料夾
2. 按 **① 分析**：只預覽，不動任何檔案
3. 切換上方選項檢查結果（不需重新分析）
4. 按 **② 執行**
5. 不滿意可按 **復原上一次**

![主畫面](docs/images/screenshot-rename.png)

### 兩種輸出方式

| 輸出方式 | 結果範例 |
|---|---|
| 改檔名 | `DSC_1234.JPG` → `8粉6藍_DSC_1234.JPG`（前＝臉、後＝整體） |
| 分資料夾 | `DSC_1234.JPG` → `膚色8粉\整體6藍\DSC_1234.JPG` |

### 顏色代碼
數字決定排列順序（彩虹順序）：

| 0白 | 1紅 | 2橙 | 3黃 | 4綠 | 5青 | 6藍 | 7紫 | 8粉 | 9暗 | 無 |
|---|---|---|---|---|---|---|---|---|---|---|
| 白光／自然膚色 | | | | | | | | | 太暗 | 沒偵測到臉 |

### 在 Lightroom Classic 依顏色排列
圖庫模組 → 格線檢視（`G`）→ 下方工具列「排序方式」選 **檔案名稱**。
也可以用「圖庫過濾器 → 文字 → 檔案名稱」輸入 `6藍`，只看臉被藍光照到的照片，一次套用同一組調色。

### 選項說明
| 選項 | 說明 |
|---|---|
| 依據 | 膚色＋整體／只看膚色／只看整體 |
| 優先 | 膚色或整體放前面（決定排序先依哪一項） |
| 加排序數字 | 不勾選時檔名更短（`粉藍_`），同色仍會排在一起 |
| 包含子資料夾 | 一併處理子資料夾（會自動略過本工具建立的顏色資料夾） |

---

## 運作原理
- **人臉偵測**：使用 OpenCV 的 [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) 深度學習模型找出人臉位置（只判斷「哪裡有臉」，**不辨識是誰**）。不受燈光顏色影響，遠景小臉也能偵測。
- **膚色判斷**：取每張臉中央區域的像素，統計色相，以最多數的顏色為準；臉越大、信心越高權重越大。
- **整體主色**：忽略黑暗區域，以明亮的有色光為主統計色相。

判斷靈敏度可在 `photo_color_sorter.py` 開頭調整（`FACE_SCORE`、`SKIN_NATURAL_S`、`NEUTRAL_S`）。

## 命令列（選用）
```bash
python photo_color_sorter.py "D:\照片\活動" --preview                  # 預覽改檔名
python photo_color_sorter.py "D:\照片\活動" --preview --output folder  # 預覽分資料夾
python photo_color_sorter.py "D:\照片\活動" --apply                    # 實際執行
```
其他參數：`--mode both|skin|main`、`--order skin|main`、`--no-digits`、`-r`（含子資料夾）

## 開發
```bash
python -m unittest discover tests   # 執行測試
build_exe.bat                       # 打包成 exe（輸出到 dist\PhotoColorSorter）
python docs\build_tutorial.py       # 重新產生教學 PDF
```

## 安全性
所有改名與復原都限制在所選資料夾內、不覆蓋既有檔案、紀錄檔防竄改、模型檔有 SHA-256 驗證。詳見 [SECURITY.md](SECURITY.md)。發現漏洞請用 GitHub 的 **Security → Report a vulnerability** 私下回報。

## 授權與免責聲明
本專案採用 **[PolyForm Noncommercial License 1.0.0](LICENSE)**，版權所有 © 2026 ting2303。

| 可以 ✅ | 不可以 ❌ |
|---|---|
| 個人免費使用（包含整理自己拍的照片） | 販售本工具或其修改版本 |
| 學生、社團、學校、非營利組織使用 | 將本工具放進付費產品或付費服務 |
| 閱讀、修改原始碼，非商業分享 | 移除作者版權聲明（`Required Notice`） |

- 分享或修改時，必須保留 LICENSE 檔案與作者聲明
- **商業授權**請透過 GitHub 聯絡 [ting2303](https://github.com/ting2303)
- 使用前請詳閱 **[免責聲明 DISCLAIMER.md](DISCLAIMER.md)**：本工具依現狀提供，不提供任何擔保；因使用造成的任何損失，作者概不負責
- 第三方元件授權見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- Adobe、Lightroom 為 Adobe Inc. 的商標，本專案與 Adobe 無關

---

## English
**Photo Color Sorter** analyzes stage/concert photos and detects (1) the color of the light falling on performers' faces and (2) the dominant color of the whole image, then renames files with a sortable color prefix or sorts them into color folders — so Lightroom Classic can sort by filename and group shots by lighting. Runs fully offline on Windows; just download the ~60 MB app, unzip and run — no Python setup needed (download from [Releases](../../releases/latest)). Files are only renamed or moved, never modified or deleted, and every run can be undone.

**License:** [PolyForm Noncommercial 1.0.0](LICENSE) — free for personal and noncommercial use; **commercial use is not permitted** without a separate license from the author (contact [ting2303](https://github.com/ting2303)). Please read [DISCLAIMER.md](DISCLAIMER.md) before use. If you find it useful, a ⭐ is appreciated!
