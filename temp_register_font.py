import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

path = 'C:/Windows/Fonts/Nirmala.ttc'
print('path:', path)
print('exists:', os.path.exists(path))
try:
    font = TTFont('NirmalaTest', path)
    pdfmetrics.registerFont(font)
    print('registered:', 'NirmalaTest' in pdfmetrics.getRegisteredFontNames())
except Exception as e:
    print('error:', type(e).__name__, str(e))
