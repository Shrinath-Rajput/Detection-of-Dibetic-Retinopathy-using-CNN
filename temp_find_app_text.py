from pathlib import Path
p=Path('app.py')
text=p.read_text()
for i,line in enumerate(text.splitlines(),1):
    if "('FONT', (0, 0), (-1, -1), 'Helvetica', 10)" in line or "('FONT', (0, 0), (-1, -1), 'Helvetica', 9)" in line or "fontName='Helvetica-Bold'" in line:
        print(i, line)
