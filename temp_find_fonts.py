import os
fonts_dir = os.path.join(os.environ.get('WINDIR', 'C:\Windows'), 'Fonts')
print('Fonts dir:', fonts_dir)
patterns = ['devanagari', 'nirmala', 'mangal', 'notosansdevanagari', 'notoserifdevanagari', 'lohit', 'hind', 'mukta', 'arialunicode', 'dejavusans', 'unicode']
matches = []
all_fonts = []
for root, dirs, files in os.walk(fonts_dir):
    for f in files:
        if f.lower().endswith(('.ttf', '.otf')):
            all_fonts.append(f)
            if any(p in f.lower() for p in patterns):
                matches.append(f)
                print('MATCH:', f)
print('Total font files:', len(all_fonts))
print('Total matches:', len(matches))
print('First 50 fonts:')
for f in sorted(all_fonts)[:50]:
    print('  ', f)
