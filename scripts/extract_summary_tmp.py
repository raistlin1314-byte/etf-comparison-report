import re, sys
sys.stdout.reconfigure(encoding='utf-8')
html = open(r'C:\Users\frank\.openclaw-tdxclaw\workspace\reports\index.html', encoding='utf-8').read()

pat = re.compile(r'\{"date":"(\d{8})","date_label":"[\d-]+","index":([\d.]+),"etfs":\[([\d.,\s]+)\]\}')
blocks = re.split(r'"index_name":"', html)

# For 510310 (block 2, col 1) and 588000 (block 6, col 0): show series around transitions
for b in blocks[1:]:
    title = b[:10].split('"')[0]
    rows_m = pat.findall(b)
    if not rows_m:
        continue
    names = re.findall(r'"name":"([^"]+)"', b)[:4]
    print('=== ' + title + ' (' + ', '.join(names) + ') ===')
    ncol = len(rows_m[0][2].split(','))
    for col in range(ncol):
        # find scale transitions: value/prev ratio > 5 or < 0.2
        prev_v = None
        for i, r in enumerate(rows_m):
            v = float(r[2].split(',')[col])
            if prev_v is not None and prev_v > 0:
                ratio = v / prev_v
                if ratio > 5 or ratio < 0.2:
                    print(f'  [{names[col]}] row {i}: {r[0]} v={v} prev={prev_v} ratio={ratio:.1f}')
                    # show context
                    for j in range(max(0,i-2), min(len(rows_m), i+3)):
                        vv = float(rows_m[j][2].split(',')[col])
                        print(f'      {rows_m[j][0]}: {vv}')
            prev_v = v
    print()
