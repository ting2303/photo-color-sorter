# -*- coding: utf-8 -*-
"""產生 docs/使用教學.pdf（需要 reportlab：pip install reportlab）。
字型預設用 Windows 內建的微軟正黑體；其他系統可用環境變數 PCS_FONT、PCS_FONT_BOLD 指定 TrueType 字型檔"""
import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from photo_color_sorter import __version__  # noqa: E402

FONT_DIR = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
pdfmetrics.registerFont(TTFont('JH', os.environ.get('PCS_FONT') or os.path.join(FONT_DIR, 'msjh.ttc'), subfontIndex=0))
pdfmetrics.registerFont(TTFont('JHB', os.environ.get('PCS_FONT_BOLD') or os.path.join(FONT_DIR, 'msjhbd.ttc'), subfontIndex=0))
pdfmetrics.registerFontFamily('JH', normal='JH', bold='JHB', italic='JH', boldItalic='JHB')  # 讓 <b> 用粗體字型
TOTAL_PAGES = 4

INK, MUTED, LINE = colors.HexColor('#1f2328'), colors.HexColor('#59636e'), colors.HexColor('#d8dee4')
ACCENT, SOFT = colors.HexColor('#3b5bdb'), colors.HexColor('#f3f5fa')
WARN_BG, WARN = colors.HexColor('#fff4e5'), colors.HexColor('#9a4f00')
CONTENT_W = 174 * mm

S = {
    'title': ParagraphStyle('t', fontName='JHB', fontSize=24, leading=32, textColor=colors.white),
    'tsub': ParagraphStyle('ts', fontName='JH', fontSize=11, leading=17, textColor=colors.HexColor('#d0d7de')),
    'h1': ParagraphStyle('h1', fontName='JHB', fontSize=17, leading=24, textColor=INK, spaceBefore=6, spaceAfter=8),
    'body': ParagraphStyle('b', fontName='JH', fontSize=11, leading=18, textColor=INK),
    'small': ParagraphStyle('s', fontName='JH', fontSize=9, leading=13.5, textColor=MUTED),
    'step': ParagraphStyle('st', fontName='JHB', fontSize=20, leading=24, textColor=colors.white, alignment=1),
    'stitle': ParagraphStyle('stt', fontName='JHB', fontSize=12.5, leading=19, textColor=INK),
    'cellc': ParagraphStyle('cc', fontName='JHB', fontSize=11, leading=14, textColor=INK, alignment=1),
    'tiny': ParagraphStyle('ti', fontName='JH', fontSize=7.5, leading=10, textColor=MUTED, alignment=1),
}
for _st in S.values():
    _st.wordWrap = 'CJK'  # 中文逐字換行，避免整段被提前斷行


def P(text, style='body'):
    return Paragraph(text, S[style])


def grid(rows, widths, style_extra=(), pad=6):
    t = Table(rows, colWidths=[w * mm for w in widths])
    t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                           ('LEFTPADDING', (0, 0), (-1, -1), pad), ('RIGHTPADDING', (0, 0), (-1, -1), pad),
                           ('TOPPADDING', (0, 0), (-1, -1), pad), ('BOTTOMPADDING', (0, 0), (-1, -1), pad)]
                          + list(style_extra)))
    return t


def box(text, bg=SOFT, fg=INK):
    st = ParagraphStyle('bx', parent=S['body'], textColor=fg, wordWrap='CJK')
    return grid([[Paragraph(text, st)]], [174], [('BACKGROUND', (0, 0), (-1, -1), bg)], pad=9)


def image(name, width_mm):
    img = Image(os.path.join(HERE, 'images', name))
    w = width_mm * mm
    img.drawHeight, img.drawWidth = img.imageHeight * w / img.imageWidth, w
    return img


def header():
    t = grid([[P('舞台照片色彩分類工具', 'title')],
              [P('Photo Color Sorter v%s　｜　使用教學　｜　© 2026 ting2303　個人與非營利使用免費，禁止商業用途' % __version__, 'tsub')]],
             [174], [('BACKGROUND', (0, 0), (-1, -1), INK),
                     ('TOPPADDING', (0, 0), (-1, 0), 14), ('BOTTOMPADDING', (0, -1), (-1, -1), 14),
                     ('LEFTPADDING', (0, 0), (-1, -1), 14)])
    return t


def legend():
    cells = [('0白', '#f2f2f2', '白光'), ('1紅', '#ffb3b3', ''), ('2橙', '#ffd6a6', ''), ('3黃', '#fff3a6', ''),
             ('4綠', '#bff0bf', ''), ('5青', '#b3f0f0', ''), ('6藍', '#b3c8ff', ''), ('7紫', '#d9b3ff', ''),
             ('8粉', '#ffb3e6', ''), ('9暗', '#b0b0b0', '太暗'), ('無', '#ffffff', '沒有臉')]
    rows = [[P(c[0], 'cellc') for c in cells], [P(c[2], 'tiny') for c in cells]]
    st = [('GRID', (0, 0), (-1, -1), 0.5, LINE)] + [('BACKGROUND', (i, 0), (i, 0), colors.HexColor(c[1]))
                                                   for i, c in enumerate(cells)]
    return grid(rows, [174 / 11] * 11, st, pad=3)


def step(num, title, body):
    return grid([[P(num, 'step'), [P(title, 'stitle'), P(body)]]], [14, 160],
                [('BACKGROUND', (0, 0), (0, 0), ACCENT), ('BACKGROUND', (1, 0), (1, 0), SOFT),
                 ('VALIGN', (0, 0), (0, 0), 'MIDDLE'), ('LEFTPADDING', (1, 0), (1, 0), 12)], pad=8)


def qa(rows, widths=(48, 126)):
    data = [[P('<b>%s</b>' % q), P(a)] for q, a in rows]
    return grid(data, widths, [('LINEBELOW', (0, 0), (-1, -2), 0.5, LINE), ('VALIGN', (0, 0), (-1, -1), 'TOP')], pad=5)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('JH', 8.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 11 * mm, 'github.com/ting2303/photo-color-sorter')
    canvas.drawRightString(192 * mm, 11 * mm, '%d / %d' % (doc.page, TOTAL_PAGES))
    canvas.restoreState()


def build(out):
    st = []
    # ---- 第 1 頁：這是什麼
    st += [header(), Spacer(1, 10),
           P('拍舞台活動時燈光一直變，修圖要一張張判斷色調很花時間。這個工具會自動判斷每張照片'
             '<b>「臉被照成什麼顏色」</b>和<b>「整張照片的主色」</b>，幫你改檔名、分資料夾，或寫成 Lightroom 的星等、色標和關鍵字。'),
           Spacer(1, 8), image('examples.jpg', 174),
           P('實際判斷結果。框線是偵測到的臉（已打馬賽克），下方是「臉／整體」的顏色和產生的檔名前綴。', 'small'),
           Spacer(1, 10),
           grid([[P('<b>改檔名</b>'), P('DSC_1234.JPG　→　<b>8粉6藍_</b>DSC_1234.JPG')],
                 [P('<b>分資料夾</b>'), P('DSC_1234.JPG　→　<b>膚色8粉 \\ 整體6藍 \\</b> DSC_1234.JPG')],
                 [P('<b>LR 標籤</b>'), P('DSC_1234.ARW 檔名不變，旁邊的 .xmp 寫入星等、<b>色標</b>、關鍵字（只有 RAW，DNG 除外）')]],
                [30, 144], [('BACKGROUND', (0, 0), (0, -1), SOFT), ('GRID', (0, 0), (-1, -1), 0.5, LINE)]),
           Spacer(1, 4),
           P('檔名前面是<b>臉的顏色</b>，後面是<b>整體顏色</b>。數字是排列順序：', 'small'),
           Spacer(1, 4), legend(),
           PageBreak()]

    # ---- 第 2 頁：三步驟
    st += [P('三步驟開始使用', 'h1'),
           box('<b>注意：請在匯入 Lightroom 之前使用，並先備份原始照片。</b>已匯入的照片在外部改名，Lightroom 會找不到檔案。', WARN_BG, WARN),
           Spacer(1, 10),
           step('1', '下載並開啟',
                '到 GitHub 專案的 <b>Releases</b> 下載 <b>PhotoColorSorter-Windows.zip</b>（約 60 MB），'
                '右鍵「解壓縮全部」後雙擊 <b>PhotoColorSorter.exe</b>。<br/>'
                '<font color="#59636e">出現「Windows 已保護您的電腦」→ 點「其他資訊」→「仍要執行」。</font>'),
           Spacer(1, 6),
           step('2', '選資料夾，按「① 分析」',
                '只預覽、不會動到檔案。可以切換上方選項，表格最右欄會即時顯示結果。<br/>'
                '<font color="#59636e">小技巧：把照片資料夾直接拖到 exe 圖示上，會自動開始分析。</font>'),
           Spacer(1, 6),
           step('3', '確認後按「② 執行改名」',
                '完成！不滿意可按「<b>復原上一次</b>」還原。<br/>'
                '<font color="#59636e">想用 Lightroom 色標篩選：進階設定 → 輸出方式選「寫入 Lightroom 標籤」→ 按「② 寫入標籤」（第 3 頁）。</font>'),
           Spacer(1, 8), image('screenshot-rename.png', 112),
           P('表格依燈光段落分組，每段的標題列寫著張數、主色和「★ 先修」哪一張；上方色帶是整場的燈光時間軸，點一下就跳到那一段。', 'small'),
           Spacer(1, 6),
           grid([[P('<b>分類依據</b>'), P('膚色＋整體／只看膚色／只看整體')],
                 [P('<b>同色內依拍攝時間排列</b>'), P('檔名多一段時間序號（例如 8粉_<b>0012</b>_DSC02921），同一個顏色裡照拍攝時間排')],
                 [P('<b>進階設定</b>'), P('輸出方式、優先、加排序數字、舞台顏色、燈光段落、挑圖功能（第 3 頁）。設定會自動記住')]],
                [44, 130], [('BACKGROUND', (0, 0), (0, -1), SOFT), ('GRID', (0, 0), (-1, -1), 0.5, LINE)], pad=5),
           PageBreak()]

    # ---- 第 3 頁：挑圖輔助與進階設定
    st += [P('挑圖輔助：先修哪一張', 'h1'),
           P('分析完成後，表格會幫你標出每段該先修的照片。這些資訊<b>不會寫進檔名</b>；選「寫入 Lightroom 標籤」時會寫成星等和關鍵字。'),
           Spacer(1, 6),
           qa([('段落', '照拍攝時間切開的同燈光區段（S01、S02…）。停頓超過 60 秒或燈光換色就換段。'),
               ('代表 ★', '每段最適合先修的一張（清楚、臉大、亮度適中）。修好它，再同步給整段。'),
               ('星等', '整批相對的初篩：1 星 = 沒有臉、臉太暗或可能模糊；3 星 = 清楚、臉夠大、曝光正常。'),
               ('人數', '偵測到幾張臉。只判斷有沒有人、有幾個人，不辨認是誰。'),
               ('亮度', '亮／中／暗：臉的亮度和整批最亮的照片比，追光忽亮忽暗時可以分開同步。'),
               ('調色起點', '臉的色偏方向，例如「色溫+20 色調-12」。只是建議，不會寫入檔案。'),
               ('小方塊', '每列最左邊：左半是膚色、右半是整體主色。點「原檔名」可以直接開啟照片。')],
              (30, 144)),
           Spacer(1, 4),
           P('進階設定', 'h1'),
           image('screenshot-advanced.png', 76),
           Spacer(1, 4),
           qa([('舞台顏色', '整場燈光很淡、大部分被判成白時，改成「淡色舞台」再分析一次比較。真正的白光場景會因此被判成有色，請和「標準」對照。'),
               ('燈光段落', '自動判斷之外，可以輸入檔名號碼（例如 <b>2921, 3040</b>）從那幾張開始新段落。'),
               ('挑圖功能', '代表張、星等、亮度分組、調色起點、燈光時間軸都可以關掉。'),
               ('LR 標籤', '輸出方式選「寫入 Lightroom 標籤」：星等、色標、關鍵字寫進 RAW 旁的 .xmp，不改檔名。'
                           '色標可選<b>依人</b>或<b>依背景</b>，在過濾器「屬性」點色標篩選。已匯入的照片：先在 LR「將中繼資料儲存至檔案」，寫入後再「從檔案讀取中繼資料」。'),
               ('偏重演出者', '背景 LED 螢幕很花時勾選，演出者周圍的顏色比背景更重要。')],
              (30, 144)),
           PageBreak()]

    # ---- 第 4 頁：分析報告、還原檔名、Lightroom、問答、安全與免責
    st += [P('分析報告與修圖後還原檔名', 'h1'),
           grid([[image('screenshot-report.png', 50),
                  [P('<b>分析報告</b>（按「分析報告」）'),
                   P('整批的統計，以及這次結果需要注意的地方和建議的調整方式。'
                     '提醒依輕重分色：<font color="#9a4f00"><b>橘色</b>需要注意</font>、<font color="#1d4a8a"><b>藍色</b>參考</font>、'
                     '<font color="#17663a"><b>綠色</b>正常</font>。'),
                   Spacer(1, 6),
                   P('<b>修圖後還原檔名</b>（選單「工具」）'),
                   P('輸出的 JPG 會帶著顏色前綴，選輸出資料夾執行後就會改回來：<br/>'
                     '8粉_0012_DSC02921-Enhanced-NR.jpg<br/>→ <b>DSC02921-Enhanced-NR.jpg</b><br/>'
                     '輸出和原始照片不在同一處時，會請你選原始資料夾。')]]],
                [58, 116], [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (0, 0), 0)], pad=3),
           P('在 Lightroom 依顏色排列', 'h1'),
           P('圖庫模組 → 格線檢視（<b>G</b>）→ 下方工具列「排序方式」選 <b>檔案名稱</b>。'
             '只看某種光：「圖庫過濾器 → 文字 → 檔案名稱」輸入例如 <b>6藍</b>；用 LR 標籤時在「屬性」點<b>色標</b>'
             '（顯示白色時，把「色標名稱」改成 LR 色標組的名稱）。'),
           P('常見問題', 'h1'),
           qa([('判斷錯了？', '自動判斷可能有誤（例如背景圖案被當成臉）。可手動改名，或按「復原上一次」換個選項再試。'),
               ('大部分都是「白」？', '燈光很淡的舞台常見。可以改「只看膚色」，或在進階設定試「淡色舞台」。'),
               ('很多照片是「無」？', '沒偵測到臉：背對、臉太小或太暗。它們會排在最後，方便另外處理。'),
               ('會弄壞照片嗎？', '不會。不修改、不刪除照片，只改名、搬移，或新增修改 RAW 旁的 .xmp（復原時會刪掉自己新建的）。'),
               ('照片會上傳嗎？', '不會。全部在你的電腦離線處理；只找「哪裡有臉」，不辨識是誰。')], (40, 134)),
           Spacer(1, 4),
           P('授權與免責聲明', 'h1'),
           qa([('授權', 'PolyForm Noncommercial 1.0.0，© 2026 ting2303。<b>個人與非營利使用免費，禁止販售或用於商業產品、服務。</b>'
                       '商業授權請聯絡作者。'),
               ('免責', '本工具依現狀提供，不提供任何擔保。因使用造成的檔案遺失、錯亂或其他損失，作者概不負責。'
                       '照片人物的肖像權與個資保護由使用者自行負責。Adobe、Lightroom 為 Adobe Inc. 的商標，本工具與 Adobe 無關。'
                       '完整條款見 LICENSE、DISCLAIMER.md、THIRD_PARTY_NOTICES.md。'),
               ('驗證下載', 'PowerShell 執行 <b>Get-FileHash .\\PhotoColorSorter-Windows.zip -Algorithm SHA256</b>，'
                        '和 Release 頁面的 SHA-256 相同即可。')], (28, 146)),
           ]

    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title='舞台照片色彩分類工具 使用教學', author='ting2303',
                            subject='Photo Color Sorter v%s 使用教學' % __version__)
    doc.build(st, onFirstPage=footer, onLaterPages=footer)


if __name__ == '__main__':
    out = os.path.join(HERE, '使用教學.pdf')
    build(out)
    print(out)
