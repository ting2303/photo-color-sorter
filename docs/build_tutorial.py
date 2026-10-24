# -*- coding: utf-8 -*-
"""產生 docs/使用教學.pdf（需要 Windows 內建的微軟正黑體與 reportlab：pip install reportlab）"""
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
pdfmetrics.registerFont(TTFont('JH', os.path.join(FONT_DIR, 'msjh.ttc'), subfontIndex=0))
pdfmetrics.registerFont(TTFont('JHB', os.path.join(FONT_DIR, 'msjhbd.ttc'), subfontIndex=0))

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
    canvas.drawRightString(192 * mm, 11 * mm, '%d / 3' % doc.page)
    canvas.restoreState()


def build(out):
    st = []
    # ---- 第 1 頁：這是什麼
    st += [header(), Spacer(1, 10),
           P('拍舞台活動時燈光一直變，修圖要一張張判斷色調很花時間。這個工具會自動判斷每張照片'
             '<b>「臉被照成什麼顏色」</b>和<b>「整張照片的主色」</b>，幫你改檔名或分資料夾。'),
           Spacer(1, 8), image('examples.jpg', 174),
           P('實際判斷結果。框線是偵測到的臉（已打馬賽克），下方是「臉／整體」的顏色和產生的檔名前綴。', 'small'),
           Spacer(1, 10),
           grid([[P('<b>改檔名</b>'), P('DSC_1234.JPG　→　<b>8粉6藍_</b>DSC_1234.JPG')],
                 [P('<b>分資料夾</b>'), P('DSC_1234.JPG　→　<b>膚色8粉 \\ 整體6藍 \\</b> DSC_1234.JPG')]],
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
           step('3', '確認後按「② 執行」',
                '完成！不滿意可按「<b>復原上一次</b>」，所有檔案會恢復原樣。'),
           Spacer(1, 10), image('screenshot-rename.png', 150),
           Spacer(1, 8),
           grid([[P('<b>輸出方式</b>'), P('改檔名　或　分資料夾')],
                 [P('<b>依據</b>'), P('膚色＋整體／只看膚色／只看整體')],
                 [P('<b>優先</b>'), P('膚色或整體放前面（排序先看哪一項）')],
                 [P('<b>加排序數字</b>'), P('不勾選檔名更短，例如 粉藍_')]],
                [34, 140], [('BACKGROUND', (0, 0), (0, -1), SOFT), ('GRID', (0, 0), (-1, -1), 0.5, LINE)], pad=5),
           PageBreak()]

    # ---- 第 3 頁：Lightroom、問答、安全與免責
    st += [P('在 Lightroom 依顏色排列', 'h1'),
           P('圖庫模組 → 格線檢視（<b>G</b>）→ 下方工具列「排序方式」選 <b>檔案名稱</b>。'),
           P('想只看某種光？「圖庫過濾器 → 文字 → 檔案名稱」輸入例如 <b>6藍</b>，調好一張再同步到同組照片。'),
           Spacer(1, 6),
           P('常見問題', 'h1'),
           qa([('判斷錯了？', '自動判斷可能有誤（例如背景圖案被當成臉）。可手動改名，或按「復原上一次」換個選項再試。'),
               ('很多照片是「無」？', '沒偵測到臉：背對、臉太小或太暗。它們會排在最後，方便另外處理。'),
               ('會弄壞照片嗎？', '不會。只改名或搬移，不修改內容、不刪檔，也只動所選資料夾內的照片。'),
               ('照片會上傳嗎？', '不會。全部在你的電腦離線處理；只找「哪裡有臉」，不辨識是誰。'),
               ('網路磁碟很慢？', '先把照片複製到本機硬碟再分析會快很多。')]),
           Spacer(1, 6),
           P('授權與免責聲明', 'h1'),
           qa([('授權', 'PolyForm Noncommercial 1.0.0，© 2026 ting2303。<b>個人與非營利使用免費，禁止販售或用於商業產品、服務。</b>'
                       '商業授權請聯絡作者。'),
               ('免責', '本工具依現狀提供，不提供任何擔保。因使用造成的檔案遺失、錯亂或其他損失，作者概不負責。'
                       '照片人物的肖像權與個資保護由使用者自行負責。'),
               ('商標', 'Adobe、Lightroom 為 Adobe Inc. 的商標，本工具與 Adobe 無關。'),
               ('完整條款', '請見 LICENSE、DISCLAIMER.md、THIRD_PARTY_NOTICES.md。')], (28, 146)),
           Spacer(1, 10),
           box('驗證下載檔（選用）：PowerShell 執行 <b>Get-FileHash .\\PhotoColorSorter-Windows.zip</b>，'
               '結果與 Release 頁面公布的 SHA-256 相同，就代表檔案沒被竄改。'),
           ]

    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title='舞台照片色彩分類工具 使用教學', author='ting2303',
                            subject='Photo Color Sorter v%s 使用教學' % __version__)
    doc.build(st, onFirstPage=footer, onLaterPages=footer)


if __name__ == '__main__':
    out = os.path.join(HERE, '使用教學.pdf')
    build(out)
    print(out)
