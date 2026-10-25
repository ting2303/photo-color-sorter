# Photo Color Sorter

[中文](README.md) | **English**

When you shoot dance shows and concerts, the stage lighting changes every few seconds. Back at the computer, the slow part of editing a few hundred shots is often not the grading itself — it's finding all the photos that were taken under the same light.

This tool looks at every photo for you: **what color of light is falling on the performers' faces**, and **what the dominant color of the frame is**. It writes the result into the filename or sorts the photos into matching folders. Import into Lightroom Classic, sort by filename, and shots under the same lighting line up next to each other — edit one, then sync the rest.

![Detection examples](docs/images/examples.jpg)

<sub>Real results (faces pixelated). Boxes mark detected faces; the bar shows the face color, the overall color, and the prefix written to the filename. Color names are in Chinese: 紅 red, 橙 orange, 藍 blue, 粉 pink.</sub>

## Download

### [⬇ Download PhotoColorSorter-Windows.zip (about 60 MB)](https://github.com/ting2303/photo-color-sorter/releases/latest/download/PhotoColorSorter-Windows.zip)

Right-click the ZIP → **Extract All**, then run `PhotoColorSorter.exe` inside the folder.

> Use the link above or the [Releases](../../releases/latest) page. The green **Code → Download ZIP** button gives you the source code, which does not include the exe.

- Requires Windows 10 or 11. No Python installation needed.
- On first launch Windows may show "Windows protected your PC" because the app is not code-signed. Click **More info → Run anyway**. To check the download hasn't been tampered with, compare its SHA-256 with the value on the Release page (see [SECURITY.md](SECURITY.md)).
- The interface and the [tutorial PDF](docs/使用教學.pdf) are in Traditional Chinese.

## How to use

> **Run it before importing into Lightroom, and back up your originals first.** If photos are renamed outside Lightroom after import, Lightroom will lose track of them.

1. Choose a photo folder
2. Click **① 分析** (Analyze). This only reads the photos; nothing is changed
3. Review the table. Changing the options updates the result column instantly — no need to re-analyze
4. Click **② 執行** (Apply)
5. Not happy? Click **復原上一次** (Undo last run) to restore everything

You can also drag a folder onto `PhotoColorSorter.exe`; the app opens and starts analyzing right away.

![App window](docs/images/screenshot-rename.png)

### Output

| Mode | Before | After |
|---|---|---|
| Rename | `DSC_1234.JPG` | `8粉6藍_DSC_1234.JPG` |
| Folders | `DSC_1234.JPG` | `膚色8粉\整體6藍\DSC_1234.JPG` |

In `8粉6藍_`, the first part (`8粉`, pink) is the face color and the second (`6藍`, blue) is the overall color.

### Color codes

| Code | Meaning |
|---|---|
| `0白` | White light. In the face position it means natural skin tone, not tinted by colored light |
| `1紅` red, `2橙` orange, `3黃` yellow, `4綠` green, `5青` cyan, `6藍` blue, `7紫` purple, `8粉` pink | Lit by that color |
| `9暗` | Too dark to judge |
| `無` | No face detected (turned away, too small, or too dark). Face position only |

The digits exist only for sorting: Lightroom sorts 0 → 9, so white light comes first, then colors in rainbow order, and "no face" last.

### Options

| Option | What it does |
|---|---|
| 依據 (Based on) | Face and overall color, face only, or overall only |
| 優先 (Priority) | Whether the face or overall color comes first, i.e. which one groups the sort |
| 加排序數字 (Sort digits) | Turn off for shorter names like `粉藍_`; same colors still group together, just not in rainbow order |
| 包含子資料夾 (Subfolders) | Include subfolders; color folders created by the tool are skipped |
| 同色內依拍攝時間排列 (Time order within a color) | Adds a capture-time sequence number after the color (e.g. `8粉_0012_DSC02921.ARW`), so photos of one color always sort by capture time, even with two cameras or a counter that restarted. Combine with face-only or overall-only to group by one color, then by time |

### Sorting in Lightroom Classic

In the Library module press `G` for Grid view, then set **Sort** in the toolbar to **File Name**.

To work on one lighting look at a time, use **Library Filter → Text → Filename** and type e.g. `6藍`.

## Picking helpers

After analysis the table shows a few extra columns to help you decide what to edit first. They only appear in the table; filenames and the result of "② 執行" are unchanged.

| Column | Meaning |
|---|---|
| 拍攝時間 (capture time) | Read from EXIF; falls back to the file time, marked with `*` |
| 段落 (scene) | Sections split by time and lighting (S01, S02…): a pause over 60 s or a light change starts a new one |
| 代表 (pick) | ★ marks the best photo to edit first in each scene (sharp, large face, good exposure). Edit it, then sync to the scene |
| 清晰度 (sharpness) | Relative score 0–100 within the batch |
| `?` after 整體 | Low vote share for the overall color; the frame is mixed, check it yourself |
| 星等 (stars) | Automatic 1–3 star pre-pick, relative to the batch: 1 = no face, face too dark or likely blurred, 3 = sharp, large face, good exposure |
| 人物 (person) | Photos of the same person share a group (P1 has the most photos). It only compares faces; it does not identify anyone. Heavy makeup, profiles or small faces can split one person into two groups |
| 亮度 (brightness) | 亮/中/暗 (bright/mid/dim) compared with that person's brightest photos, so spotlight changes within a song can be synced separately |
| 調色起點 (WB start) | Direction and strength of the face color cast, e.g. 色溫+20 色調-12 = warmer and greener. A suggestion only: nothing is written to files, and the numbers are not exact Lightroom slider values |

The main window keeps only the common settings. Everything else is under 進階設定 (advanced, press 進階設定 ▸), less-used tools are in the 工具 (tools) menu, and all columns are under 顯示 → 顯示所有欄位 (view → all columns).

Manual controls in the advanced panel:

- **燈光段落 (scenes): auto / manual / auto + manual**: type file numbers (e.g. `2921, 3040, 3074`) to start a new scene at those photos. Without an exact match the nearest larger number is used; numbers that match nothing are listed in the status bar
- **舞台顏色 (stage color): standard / pale**: try 淡色舞台 (pale) when the whole show's lighting is faint and most photos come out white. The trade-off: genuine white-light scenes get classed as colored, and already-graded photos tend to read skin as red light, so compare with standard before using it. The analysis report warns about this
- **挑圖功能 (picking features)**: picks, stars, person groups, brightness groups, WB start and the lighting timeline can each be turned on or off. Turning off person groups makes analysis much faster

Your last settings are remembered (saved as `.photo_color_sorter.json` in your user folder).

Reading aids:

- When sorted by capture time, the table is grouped by scene with a header row per scene (count, main color, time span, which photo to edit first); scenes can be collapsed
- Each row starts with a small swatch: left half = face color, right half = overall color; the legend uses color chips too
- A **lighting timeline** strip above the table shows the whole show; click it to jump to that scene. Pauses longer than 10 minutes (intermissions, a wrong camera clock) are compressed so they don't squeeze everything else together
- Report notes are color-coded: ⚠ attention, ℹ info, ✓ OK

Other options:

- **整體偏重演出者 (weight the performer)**: tick it when the LED wall behind is very colorful, so the light around the performer counts more
- **表格排序 (table order)**: by capture time, filename, color, person or stars (features that are turned off can't be used for sorting)
- **匯出 CSV (export CSV)**: saves the table into the photo folder; opens in Excel
- **Large lighting timeline**: 工具 → 燈光時間軸 (tools → lighting timeline) opens a bigger view of the show's lighting, scene boundaries and picks
- **分析報告 (analysis report)**: batch statistics plus anything to watch out for (e.g. most photos classed white, no capture times, many photos without a detected face) and what to change. The status bar also says how many items need attention

## Restoring names after editing

After editing RAW files and exporting JPGs, the exported names usually still carry the color prefix, and editors often add a suffix, e.g. `8粉_0012_DSC02921-Enhanced-NR.jpg`.

Choose the export folder in the app and use 工具 → 還原修圖後檔名… (tools → restore edited names) to get `DSC02921-Enhanced-NR.jpg`: only the part this tool added is removed, the suffix stays. With the original names back, sorting by filename follows the shooting order again.

- If the export folder is separate from the originals, the app asks for the originals folder and matches against the rename log there. This is the most precise method, and **only photos in the log are touched**; files you named yourself (e.g. `白_婚禮.jpg`) are left alone
- Only when no log is found does it fall back to removing a leading color prefix by pattern
- It lists the changes before renaming, and 復原上一次 (undo) reverts them

## How it works

- **Face detection** uses OpenCV's [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) model. It doesn't rely on color, so stage lighting doesn't throw it off, and it finds small faces in wide shots. It only finds *where* faces are — it does not identify anyone.
- **Face color**: the hue of the central area of each face is counted, and the most common color wins. Larger, more confident detections carry more weight.
- **Overall color**: dark areas are ignored; bright colored light dominates. Light bursts, starbursts and blown-out white costumes (very bright, almost colorless) do not vote, so a few bursts can no longer turn a whole photo 白 (white); as they cover more of the lit area (from 20% to 50%), their votes are gradually restored, so a largely blown-out white-light scene is still classed as white. The 燈光爆點 (light bursts) column shows that share.

Detection is automatic and will sometimes be wrong — a background graphic mistaken for a face, or cool white light read as blue. Sensitivity settings are at the top of `photo_color_sorter.py`.

## FAQ

**Can it damage my photos?**
No. It only renames or moves files. Image contents are never modified and nothing is deleted. Every run is logged and can be fully undone.

**Are photos uploaded anywhere?**
No. Everything runs locally; the app makes no network connections.

**Which formats are supported?**
JPG, PNG, TIFF, BMP, WebP, and RAW files from major brands (Canon, Nikon, Sony, Fujifilm, and others). RAW, JPG and XMP files with the same name are handled together.

**Is there a Mac version?**
Windows only for now.

<details>
<summary><b>Running from source, command line, development</b></summary>

Requires Python 3.10+:

```bash
pip install -r requirements.txt
python photo_color_sorter.py
```

Command line:

```bash
python photo_color_sorter.py "D:\Photos\Event" --preview                  # preview renaming
python photo_color_sorter.py "D:\Photos\Event" --preview --output folder  # preview folder sorting
python photo_color_sorter.py "D:\Photos\Event" --apply                    # apply
```

More flags: `--mode both|skin|main`, `--order skin|main`, `--no-digits`, `-r` (recursive), `--performer`, `--time-seq`, `--stage standard|pale`, `--scenes auto|manual|both --splits "2921,3040"`, `--csv out.csv`, `--report [report.txt]`

Restore edited names: `python photo_color_sorter.py "D:\Export" --restore --log-folder "D:\Photos\Event" --apply`

Development:

```bash
python -m unittest discover tests   # run tests
build_exe.bat                       # build the exe into dist\PhotoColorSorter
python docs\build_tutorial.py       # regenerate the tutorial PDF
```

</details>

## Security

Renames and undo operations are confined to the folder you choose, existing files are never overwritten, and an undo log that points outside that folder is rejected. Details in [SECURITY.md](SECURITY.md). Please report security issues privately via **Security → Report a vulnerability** on this page.

## License

[PolyForm Noncommercial License 1.0.0](LICENSE), © 2026 ting2303.

| Allowed | Not allowed |
|---|---|
| Personal use, including organizing photos from your own paid shoots | Selling this tool or a modified version |
| Use by schools, clubs and nonprofits | Including it in a paid product or service |
| Reading, modifying and sharing the code noncommercially | Removing the author notice in LICENSE |

For a commercial license, contact [ting2303](https://github.com/ting2303) on GitHub.

Please read the [disclaimer](DISCLAIMER.md) before use. Third-party licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Adobe and Lightroom are trademarks of Adobe Inc.; this project is not affiliated with Adobe.

---

If this saved you some time, a Star is appreciated — and feedback is welcome in [Issues](../../issues).
