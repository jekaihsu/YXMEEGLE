"""Local, read-only source PDF extraction for traceable SOP verification."""
from pathlib import Path
import json
import hashlib
import fitz

root=Path(__file__).resolve().parents[1]
out=root/'.runtime'/'sop-audit-20260928'
out.mkdir(exist_ok=True)
index=[]
for path in sorted(root.glob('*.pdf')):
    doc=fitz.open(path)
    (out/(path.stem+'.txt')).write_text('\n'.join(f'PAGE {i+1}\n'+page.get_text() for i,page in enumerate(doc)),encoding='utf-8')
    for i,page in enumerate(doc):
        page.get_pixmap(matrix=fitz.Matrix(1.3,1.3)).save(out/(path.stem+f'-{i+1}.png'))
    index.append({'file':path.name,'pages':len(doc),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
(out/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(index,ensure_ascii=False))
