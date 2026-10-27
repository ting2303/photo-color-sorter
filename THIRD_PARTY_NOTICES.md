# 第三方元件授權 Third-Party Notices

本工具使用下列第三方元件，各元件依其原始授權條款提供。

| 元件 | 用途 | 授權 | 來源 |
|---|---|---|---|
| OpenCV (opencv-python) | 影像讀取、人臉偵測 | Apache-2.0 | https://github.com/opencv/opencv-python |
| YuNet 人臉偵測模型 `face_detection_yunet_2023mar.onnx` | 偵測人臉位置 | MIT，Copyright (c) 2020 Shiqi Yu | https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet |
| SFace 人臉辨識模型 `face_recognition_sface_2021dec_int8.onnx` | 人物分組（判斷兩張臉是否同一人，不辨識身分） | Apache-2.0，Yaoyao Zhong（模型）、OpenCV Zoo（轉換與量化） | https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface |
| NumPy | 數值運算 | BSD-3-Clause | https://github.com/numpy/numpy |
| rawpy | 讀取 RAW 檔 | MIT | https://github.com/letmaik/rawpy |
| LibRaw（rawpy 內含） | RAW 解碼 | LGPL-2.1 或 CDDL-1.0 | https://github.com/LibRaw/LibRaw |
| Python／Tkinter | 執行環境與視窗介面 | PSF License | https://www.python.org |
| PyInstaller（僅用於打包 exe） | 打包 | GPL-2.0 with bootloader exception | https://github.com/pyinstaller/pyinstaller |

## YuNet 模型授權全文

```
MIT License

Copyright (c) 2020 Shiqi Yu <shiqi.yu@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## SFace 模型授權

SFace 模型（MobileFaceNet 以 SFace loss 訓練，論文 https://arxiv.org/abs/2205.12010）由 OpenCV Zoo 以 Apache License 2.0 發布，全文見 https://www.apache.org/licenses/LICENSE-2.0 。本工具未修改模型檔。

LibRaw 以動態函式庫形式隨 rawpy 提供，使用者可依 LGPL-2.1 自行替換該函式庫。
