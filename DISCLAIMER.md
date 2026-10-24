# 免責聲明 Disclaimer

使用本軟體（Photo Color Sorter，以下稱「本工具」）即表示您已閱讀並同意以下條款。

## 一、依現狀提供，不提供任何擔保
本工具以「現狀」（AS IS）免費提供，作者與貢獻者不對其正確性、完整性、穩定性或適用於特定用途作任何明示或默示的保證。

## 二、檔案安全與資料損失
1. 本工具會**改名或搬移**您的照片檔案（不會刪除或修改照片內容）。
2. **使用前請務必備份原始照片。** 因使用本工具所造成的任何檔案遺失、損毀、檔名錯亂、Lightroom 目錄連結失效或其他直接或間接損失，作者與貢獻者概不負責。
3. 本工具會留下改名紀錄（`_色彩分類紀錄_*.csv`）供復原，但無法保證在所有情況下（例如檔案被其他程式移動、磁碟錯誤、網路磁碟中斷）都能完整復原。

## 三、判斷結果僅供參考
顏色與人臉判斷是由電腦影像演算法自動產生，**可能出現誤判**（例如把背景圖案當成人臉，或冷白光被判為藍色）。分類結果僅供整理參考，請以您自己的專業判斷為準。

## 四、隱私與肖像
1. 本工具**完全在您的電腦上離線執行**，不會上傳任何照片、人臉資料或使用資訊，也不包含任何網路連線或追蹤功能。
2. 本工具僅偵測「畫面中哪裡有臉」以取樣顏色，**不進行人臉辨識（不辨認是誰）**，也不儲存任何人臉資料。
3. 照片中人物的肖像權、個人資料保護及著作權等法律責任，由使用者自行負責並遵守當地法規。

## 五、商標
Adobe、Lightroom 為 Adobe Inc. 的商標。本工具為獨立開發，與 Adobe Inc. 無任何關聯，亦未獲其認可或贊助。

## 六、第三方元件
本工具使用的第三方元件（OpenCV、NumPy、rawpy／LibRaw、YuNet 人臉模型等）依其各自授權條款提供，詳見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 七、使用授權
本工具採用 [PolyForm Noncommercial License 1.0.0](LICENSE)，版權所有 © 2026 ting2303。**僅限個人及非商業用途使用**，禁止販售或用於商業產品、服務；商業授權請另行聯絡作者。本聲明與授權條款如有不一致，以 LICENSE 為準。

## 八、條款變更
本聲明可能隨版本更新而修改，以 GitHub 儲存庫中最新版本為準。

---

## English Summary
This software is provided **"AS IS", without warranty of any kind**. It renames or moves photo files; **always back up your originals before use**. The authors are not liable for any data loss, broken Lightroom catalog links, or other damages. Color and face detection are automatic and may be wrong. All processing happens **offline on your computer**; no photos or data are uploaded, and no face *recognition* (identifying people) is performed. Users are responsible for complying with portrait-rights and privacy laws. Adobe and Lightroom are trademarks of Adobe Inc.; this project is not affiliated with or endorsed by Adobe. Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE) (Copyright © 2026 ting2303): **noncommercial use only**; contact the author for commercial licensing.
