from pathlib import Path
import pypdf

p = Path('c:/tax-agent/Form_16_template.pdf')
r = pypdf.PdfReader(str(p))
print('pages', len(r.pages))
for i, pg in enumerate(r.pages, 1):
    t = pg.extract_text() or ''
    print(f'---PAGE {i}---')
    print(t[:6000])
