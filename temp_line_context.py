from pathlib import Path
p = Path('app.py')
lines = p.read_text().splitlines()
for num in [1240,1250,1260,1270,1280,1490,1500,1510,1520,1530,1540,1550,1560,1570]:
    print(f'{num}: {lines[num-1]}')
