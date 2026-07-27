import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import black

path = 'C:/Windows/Fonts/Nirmala.ttc'
font_key = 'DevaNirmala_ttc'
pdfmetrics.registerFont(TTFont(font_key, path))

styles = getSampleStyleSheet()
style = ParagraphStyle('Test', parent=styles['Normal'], fontName=font_key, fontSize=18, textColor=black)

story = [Paragraph('यह हिंदी पाठ है। यह परीक्षण के लिए है।', style), Spacer(1, 12), Paragraph('मराठी मजकूर येथे आहे.', style)]

doc = SimpleDocTemplate('temp_nirmala.pdf', pagesize=letter)
doc.build(story)
print('wrote temp_nirmala.pdf')
