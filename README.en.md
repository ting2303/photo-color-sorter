# Photo Color Sorter

[中文](README.md) | **English**

When you shoot dance shows and concerts, the stage lighting changes every few seconds. Back at the computer, the slow part of editing a few hundred shots is often not the grading itself — it's finding all the photos that were taken under the same light.

This tool looks at every photo for you: **what color of light is falling on the performers' faces**, and **what the dominant color of the frame is**. It writes the result into the filename or sorts the photos into matching folders. Import into Lightroom Classic, sort by filename, and shots under the same lighting line up next to each other — edit one, then sync the rest.

![Detection examples](docs/images/examples.jpg)

<sub>Real results (faces pixelated). Boxes mark detected faces; the bar shows the face color, the overall color, and the prefix written to the filename. Color names are in Chinese: 紅 red, 橙 orange, 藍 blue, 粉 pink.</sub>

## Download

Get `PhotoColorSorter-Windows.zip` (about 60 MB) from [Releases](../../releases/latest), unzip it, and run `PhotoColorSorter.exe`.

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

### Sorting in Lightroom Classic

In the Library module press `G` for Grid view, then set **Sort** in the toolbar to **File Name**.

To work on one lighting look at a time, use **Library Filter → Text → Filename** and type e.g. `6藍`.

## How it works

- **Face detection** uses OpenCV's [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) model. It doesn't rely on color, so stage lighting doesn't throw it off, and it finds small faces in wide shots. It only finds *where* faces are — it does not identify anyone.
- **Face color**: the hue of the central area of each face is counted, and the most common color wins. Larger, more confident detections carry more weight.
- **Overall color**: dark areas are ignored; bright colored light dominates.

Detection is automatic and will sometimes be wrong — a background graphic mistaken for a face, or cool white light read as blue. Sensitivity settings are at the top of `photo_color_sorter.py`.

## FAQ

**Can it damage my photos?**
No. It only renames or moves files. Image contents are never modified and nothing is deleted. Every run is logged and can be fully undone.

**Are photos uploaded anywhere?**
No. Everything runs locally; the app makes no network connections.

**Which formats are supported?**
JPG, PNG, TIFF, and RAW files from major brands (Canon, Nikon, Sony, Fujifilm, and others). RAW, JPG and XMP files with the same name are handled together.

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

More flags: `--mode both|skin|main`, `--order skin|main`, `--no-digits`, `-r` (recursive)

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
