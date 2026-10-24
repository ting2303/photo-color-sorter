# -*- coding: utf-8 -*-
"""產生 docs/使用教學.pdf（需要 Windows 內建的微軟正黑體與 reportlab：pip install reportlab）"""
import os
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from photo_color_sorter import __version__  # noqa: E402

FONT_DIR = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
pdfmetrics.registerFont(TTFont('JH', os.path.join(FONT_DIR, 'msjh.ttc'), subfontIndex=0))
pdfmetrics.registerFont(TTFont('JHB', os.path.join(FONT_DIR, 'msjhbd.ttc'), subfontIndex=0))

INK, MUTED, ACCENT, SOFT = colors.HexColor('#1f2328'), colors.HexColor('#59636e'), colors.HexColor('#3b5bdb'), colors.HexColor('#f1f3f9')
WARN_BG, WARN = colors.HexColor('#fff4e5'), colors.HexColor('#b35c00')

S = {
    'title': ParagraphStyle('t', fontName='JHB', fontSize=30, leading=40, textColor=INK, alignment=TA_CENTER),
    'subtitle': ParagraphStyle('st', fontName='JH', fontSize=13, leading=22, textColor=MUTED, alignment=TA_CENTER),
    'h1': ParagraphStyle('h1', fontName='JHB', fontSize=18, leading=26, textColor=INK, spaceBefore=4, spaceAfter=10),
    'h2': ParagraphStyle('h2', fontName='JHB', fontSize=13, leading=20, textColor=ACCENT, spaceBefore=10, spaceAfter=4),
    'body': ParagraphStyle('b', fontName='JH', fontSize=10.5, leading=18, textColor=INK, spaceAfter=4),
    'small': ParagraphStyle('s', fontName='JH', fontSize=9, leading=14, textColor=MUTED),
    'code': ParagraphStyle('c', fontName='JH', fontSize=10, leading=16, textColor=INK, backColor=SOFT,
                           borderPadding=(6, 8, 6, 8), spaceBefore=4, spaceAfter=10, leftIndent=8, rightIndent=8),
    'cell': ParagraphStyle('cell', fontName='JH', fontSize=10, leading=15, textColor=INK),
    'cellc': ParagraphStyle('cellc', fontName='JHB', fontSize=11, leading=15, textColor=INK, alignment=TA_CENTER),
}


def P(text, style='body'):
    return Paragraph(text, S[style])


def box(text, bg=SOFT, fg=INK):
    t = Table([[Paragraph(text, ParagraphStyle('bx', parent=S['body'], textColor=fg, spaceAfter=0))]], colWidths=[170 * mm])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), bg), ('BOX', (0, 0), (-1, -1), 0, bg),
                           ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                           ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    return t


def table(rows, widths, header=True):
    data = [[Paragraph(str(c), S['cell']) for c in r] for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths])
    style = [('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#d0d7de')),
             ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
             ('LEFTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]
    if header:
        style.append(('BACKGROUND', (0, 0), (-1, 0), SOFT))
    t.setStyle(TableStyle(style))
    return t


def screenshot(name, caption, width=170):
    path = os.path.join(HERE, 'images', name)
    img = Image(path)
    w = width * mm
    img.drawHeight, img.drawWidth = img.imageHeight * w / img.imageWidth, w
    return KeepTogether([img, Spacer(1, 3), P(caption, 'small'), Spacer(1, 8)])


def color_legend():
    cells = [('0白', '#f2f2f2', '白光／自然膚色'), ('1紅', '#ffb3b3', ''), ('2橙', '#ffd6a6', ''), ('3黃', '#fff3a6', ''),
             ('4綠', '#bff0bf', ''), ('5青', '#b3f0f0', ''), ('6藍', '#b3c8ff', ''), ('7紫', '#d9b3ff', ''),
             ('8粉', '#ffb3e6', ''), ('9暗', '#9a9a9a', '太暗'), ('無', '#ffffff', '沒偵測到臉')]
    row1 = [Paragraph(c[0], S['cellc']) for c in cells]
    row2 = [Paragraph(c[2], ParagraphStyle('lg', parent=S['small'], alignment=TA_CENTER, fontSize=7.5, leading=10)) for c in cells]
    t = Table([row1, row2], colWidths=[15.4 * mm] * len(cells))
    st = [('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#d0d7de')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]
    st += [('BACKGROUND', (i, 0), (i, 0), colors.HexColor(c[1])) for i, c in enumerate(cells)]
    t.setStyle(TableStyle(st))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('JH', 8.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 12 * mm, '舞台照片色彩分類工具 Photo Color Sorter v%s 使用教學' % __version__)
    canvas.drawRightString(190 * mm, 12 * mm, '第 %d 頁' % doc.page)
    canvas.restoreState()


def build(out):
    st = []
    # ---- 封面
    st += [Spacer(1, 60 * mm), P('舞台照片色彩分類工具', 'title'), Spacer(1, 6),
           P('Photo Color Sorter　v%s　使用教學' % __version__, 'subtitle'), Spacer(1, 14),
           P('自動判斷「臉被照成什麼顏色」與「整張照片的主色」<br/>一鍵改檔名或分資料夾，匯入 Lightroom 就依顏色排好', 'subtitle'),
           Spacer(1, 70 * mm),
           P('免費開源（MIT 授權）・完全離線執行・不上傳任何照片', 'subtitle'), PageBreak()]

    # ---- 1 功能介紹
    st += [P('1　這個工具能做什麼', 'h1'),
           P('拍攝舞台活動時，燈光不斷切換、造型燈顏色很雜，修圖時常要一張張判斷色調。本工具會自動分析每張照片，幫你做兩件事：'),
           table([['分析項目', '說明'],
                  ['膚色', '找出畫面中的人臉，判斷臉上「大多數」被照成什麼顏色。例如藍光打在臉上就是「藍」，一般白光就是「白」。'],
                  ['整體主色', '判斷整張照片的主要顏色。會忽略黑暗區域，以明亮的有色燈光為主。']], [32, 138]),
           Spacer(1, 10),
           P('判斷完成後，你可以選擇兩種整理方式：'),
           table([['輸出方式', '範例', '適合'],
                  ['改檔名', '8粉6藍_DSC_1234.JPG', '不想分資料夾，在 Lightroom 用檔名排序'],
                  ['分資料夾', '膚色8粉 \\ 整體6藍 \\ DSC_1234.JPG', '想直接在檔案總管分好類']], [26, 72, 72]),
           P('顏色代碼', 'h2'),
           P('每個顏色前面的數字代表排列順序，讓 Lightroom 依彩虹順序排列：'),
           color_legend(), Spacer(1, 8),
           P('改檔名時，<b>前面是優先項目（預設是膚色），後面是另一項</b>。例如 <b>8粉6藍_</b> 代表「臉是粉色、整體是藍色」。'),
           box('支援格式：JPG、PNG、TIFF，以及 Canon、Nikon、Sony、Fujifilm 等主流 RAW 檔。同名的 RAW、JPG、XMP 會一起處理。'),
           PageBreak()]

    # ---- 2 下載安裝
    st += [P('2　下載與開啟', 'h1'),
           P('<b>不需要安裝 Python 或任何軟體</b>，下載解壓縮就能用（僅支援 Windows 10／11）。', 'body'),
           table([['步驟', '操作'],
                  ['1', '到本專案的 GitHub 頁面，點右側的 <b>Releases</b>，下載 <b>PhotoColorSorter-Windows.zip</b>。'],
                  ['2', '在 ZIP 檔上按右鍵 →「解壓縮全部」。<b>請勿直接在 ZIP 裡面執行。</b>'],
                  ['3', '打開解壓縮後的資料夾，雙擊 <b>PhotoColorSorter.exe</b>。'],
                  ['4', '第一次執行若出現「Windows 已保護您的電腦」，點「<b>其他資訊</b>」→「<b>仍要執行</b>」。']], [14, 156]),
           Spacer(1, 8),
           box('為什麼會出現 Windows 保護提示？因為本工具是免費開源軟體，沒有購買數位簽章憑證。'
               '請只從本專案的 GitHub Releases 下載。若想確認檔案沒被竄改，可比對 Release 頁面公布的 SHA-256（見第 7 章）。', WARN_BG, WARN),
           P('小技巧：直接把照片資料夾拖到程式圖示上', 'h2'),
           P('把照片資料夾拖曳到 PhotoColorSorter.exe 上放開，程式會自動打開並開始分析該資料夾。'),
           PageBreak()]

    # ---- 3 使用步驟
    st += [P('3　使用步驟', 'h1'),
           box('<b>重要：請在「匯入 Lightroom 之前」執行，並先備份原始照片。</b>'
               '已經匯入 Lightroom 的照片若在外部改名或搬移，Lightroom 會顯示「找不到檔案」。', WARN_BG, WARN),
           Spacer(1, 8),
           table([['步驟', '操作'],
                  ['①', '按「<b>選擇…</b>」挑選照片資料夾。有子資料夾的話勾選「包含子資料夾」。'],
                  ['②', '按「<b>① 分析（預覽，不動檔案）</b>」。這一步只會讀取照片，不會改任何東西。'],
                  ['③', '在表格中檢查結果。可以切換上方的選項，「結果」欄會即時更新，<b>不需要重新分析</b>。'],
                  ['④', '確認沒問題後按「<b>② 執行改名</b>」（或「② 執行分資料夾」），再按「是」確認。'],
                  ['⑤', '不滿意可以按「<b>復原上一次</b>」，所有檔案會恢復原樣。']], [14, 156]),
           Spacer(1, 10),
           screenshot('screenshot-rename.png', '圖 1　分析完成後的畫面（改檔名模式）。表格底色代表排序依據的顏色。', 140),
           P('選項說明', 'h2'),
           table([['選項', '說明'],
                  ['輸出方式', '改檔名，或分資料夾。'],
                  ['依據', '膚色＋整體／只看膚色／只看整體。只看一項時，檔名或資料夾也只會有一個顏色。'],
                  ['優先', '決定「膚色」或「整體」放在前面，也就是排序時先依哪一項分組。'],
                  ['加排序數字', '勾選時依彩虹順序排列；不勾選檔名更短（例如 粉藍_），同色仍會排在一起。'],
                  ['移除所有顏色前綴', '把資料夾內所有照片的顏色前綴去掉，恢復原檔名。']], [36, 134]),
           PageBreak()]

    # ---- 4 分資料夾
    st += [P('4　分資料夾模式', 'h1'),
           P('在「輸出方式」選擇「<b>分資料夾</b>」，按鈕會變成「② 執行分資料夾」。照片會被搬到所選資料夾內的顏色子資料夾，檔名不變：'),
           P('範例舞台照片 \\ 膚色0白 \\ 整體6藍 \\ 20260510-KOK00849.JPG<br/>'
             '範例舞台照片 \\ 膚色8粉 \\ 整體1紅 \\ 20260510-KOK01175.JPG<br/>'
             '範例舞台照片 \\ 膚色無 \\ 整體6藍 \\ 20260510-KOK09934.JPG', 'code'),
           screenshot('screenshot-folder.png', '圖 2　分資料夾模式的預覽，「結果」欄顯示照片會被搬到哪裡。'),
           P('「復原上一次」同樣適用：照片會搬回原位，空的顏色資料夾也會一併清除。'),
           PageBreak()]

    # ---- 5 Lightroom
    st += [P('5　在 Lightroom Classic 依顏色排列', 'h1'),
           P('使用「改檔名」模式後，照常匯入 Lightroom Classic，然後：'),
           table([['步驟', '操作'],
                  ['1', '進入「<b>圖庫</b>」模組，切換到格線檢視（快捷鍵 <b>G</b>）。'],
                  ['2', '在格線下方工具列的「<b>排序方式</b>」選擇「<b>檔案名稱</b>」。（若沒看到工具列，按 <b>T</b> 顯示）'],
                  ['3', '照片就會依顏色排好：0白 → 1紅 → 2橙 → … → 8粉 → 9暗 → 無臉。']], [14, 156]),
           Spacer(1, 8),
           P('也可以在頂端「<b>圖庫過濾器</b>」選「文字」→「檔案名稱」→ 輸入例如 <b>6藍</b>，只顯示臉被藍光照到的照片，'
             '一次套用同一組調色設定，修圖速度會快很多。'),
           box('建議流程：用本工具改名 → 匯入 Lightroom → 依檔名排序 → 每個顏色群組調好一張 → 同步設定到同組其他照片。'),
           P('6　常見問題', 'h1'),
           table([['問題', '解答'],
                  ['判斷錯誤怎麼辦？', '自動判斷可能有誤（例如背景圖案被當成臉、冷白光被判為藍）。可手動改名，或按「復原上一次」後調整選項再試。'],
                  ['很多照片顯示「無」？', '代表沒偵測到臉，常見於背對、側臉過大、臉太小或太暗的照片。這些會排在最後，方便另外處理。'],
                  ['分析很慢？', '速度取決於照片數量與硬碟速度。網路磁碟會比本機硬碟慢，可以先複製到本機再分析。'],
                  ['會不會弄壞照片？', '不會。本工具只「改名」或「搬移」，不修改照片內容，也不刪除任何檔案。'],
                  ['照片會被上傳嗎？', '不會。全部在你的電腦上離線處理，不連網路。'],
                  ['可以重複執行嗎？', '可以。已加過前綴的照片會先移除舊前綴再重新命名，不會疊加。']], [40, 130]),
           PageBreak()]

    # ---- 7 安全與免責
    st += [P('7　安全性', 'h1'),
           table([['本工具會', '本工具不會'],
                  ['讀取你選擇的資料夾中的照片', '連上網路、上傳資料或追蹤使用狀況'],
                  ['在同一資料夾內改名或搬移照片與同名 XMP', '刪除照片或修改照片內容'],
                  ['建立顏色資料夾與改名紀錄（_色彩分類紀錄_*.csv）', '動到所選資料夾以外的任何檔案'],
                  ['復原時刪除自己建立且已清空的顏色資料夾', '動到照片和 XMP 以外的檔案']], [85, 85]),
           Spacer(1, 8),
           P('驗證下載檔案（選用）', 'h2'),
           P('在下載的 ZIP 所在資料夾按住 Shift 按右鍵 →「在這裡開啟 PowerShell 視窗」，輸入：'),
           P('Get-FileHash .\\PhotoColorSorter-Windows.zip -Algorithm SHA256', 'code'),
           P('顯示的值與 Release 頁面公布的 SHA-256 相同，就代表檔案完整未被竄改。'),
           P('8　免責聲明', 'h1'),
           P('1. 本工具以「現狀」免費提供，不提供任何明示或默示的擔保。'),
           P('2. <b>使用前請務必備份原始照片。</b>因使用本工具造成的檔案遺失、檔名錯亂、Lightroom 連結失效或其他損失，作者與貢獻者概不負責。'),
           P('3. 顏色與人臉判斷為自動演算法產生，可能有誤，僅供整理參考。'),
           P('4. 本工具只偵測「哪裡有臉」以取樣顏色，<b>不辨識人物身分</b>，也不儲存任何人臉資料。照片中人物的肖像權與個資保護由使用者自行負責。'),
           P('5. Adobe、Lightroom 為 Adobe Inc. 的商標。本工具為獨立開發，與 Adobe Inc. 無任何關聯。'),
           P('6. 完整條款請見專案中的 DISCLAIMER.md 與 LICENSE（MIT 授權）；第三方元件授權見 THIRD_PARTY_NOTICES.md。'),
           ]

    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
                            title='舞台照片色彩分類工具 使用教學', author='photo-color-sorter contributors',
                            subject='Photo Color Sorter v%s 使用教學' % __version__)
    doc.build(st, onLaterPages=footer)


if __name__ == '__main__':
    out = os.path.join(HERE, '使用教學.pdf')
    build(out)
    print(out)
