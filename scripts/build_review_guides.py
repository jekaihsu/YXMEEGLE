"""Build public, offline HTML guides from maintained Markdown; no network."""
from pathlib import Path
import re
import html
import markdown

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'docs/guide'
CSS='''
:root{--ink:#203448;--muted:#5d6e7e;--line:#dce5eb;--brand:#126485;--paper:#fff;--bg:#f3f6f8}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.85 "Microsoft JhengHei","Noto Sans TC",sans-serif}a{color:var(--brand);text-underline-offset:3px}header{background:#16384a;color:white;padding:34px max(24px,calc((100vw - 1260px)/2));}header p{margin:0;font-size:13px;letter-spacing:.08em}header nav{display:flex;flex-wrap:wrap;gap:12px;margin-top:15px}header a{color:white;font-size:14px}main{max-width:1280px;margin:30px auto;display:grid;grid-template-columns:240px minmax(0,1fr);gap:24px;padding:0 22px}aside{position:sticky;top:20px;align-self:start;max-height:90vh;overflow:auto;padding:16px;background:white;border:1px solid var(--line);border-radius:10px;font-size:13px}aside ul{list-style:none;padding-left:12px}aside>div>ul{padding:0}aside li{margin:6px 0}article{min-width:0;background:white;padding:42px;border:1px solid var(--line);border-radius:12px}h1{font-size:32px;line-height:1.4;margin:0 0 22px}h2{font-size:23px;margin:45px 0 18px;border-top:1px solid var(--line);padding-top:24px;scroll-margin-top:20px}h3{font-size:18px;margin-top:28px}p,li{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;font-size:14px;line-height:1.7;margin:22px 0;table-layout:fixed}th{background:#eaf2f5;text-align:left}td,th{border:1px solid var(--line);padding:10px;vertical-align:top;overflow-wrap:anywhere}pre{padding:18px;border-radius:7px;background:#eef2f5;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}code{font-family:Consolas,monospace;background:#eef2f5;padding:2px 4px;font-size:.9em}pre code{padding:0}img{max-width:100%;height:auto;border:1px solid var(--line);border-radius:6px}figure{margin:24px 0}figcaption{font-size:13px;color:var(--muted)}blockquote{border-left:4px solid var(--brand);margin:20px 0;padding:8px 18px;background:#edf5f7}footer{max-width:1260px;margin:20px auto;padding:24px;color:var(--muted);font-size:13px}.print{border:1px solid white;background:transparent;color:white;padding:6px 14px;cursor:pointer;border-radius:5px}.frontnote{font-size:13px;color:var(--muted);padding-bottom:18px;border-bottom:1px solid var(--line)}@media(max-width:850px){main{display:block;padding:0 12px}aside{position:static;max-height:none;margin-bottom:18px}article{padding:22px}h1{font-size:27px}table{font-size:12px}td,th{padding:6px}header{padding:24px}}
@media print{@page{size:A4;margin:15mm 13mm}body{background:white;font-size:10pt;line-height:1.65}header,aside,footer,.print{display:none}main{display:block;margin:0;padding:0;max-width:none}article{border:0;padding:0}h1{font-size:24pt}h2{font-size:16pt;margin-top:20pt;padding-top:12pt;break-after:avoid}h3{font-size:12pt;break-after:avoid}table{font-size:8pt;line-height:1.5;table-layout:fixed}th,td{padding:5px}tr{break-inside:avoid}thead{display:table-header-group}img{max-height:220mm;object-fit:contain;display:block;margin:auto}figure{break-inside:avoid}pre{font-size:8pt;break-inside:avoid}a{color:inherit}p{orphans:3;widows:3}}
'''

def render(name):
    source=(DEST/(name+'.md')).read_text(encoding='utf-8')
    source=re.sub(r'```mermaid\n.*?```','![資料來源與輸出路徑](assets/dataflow.png)\n\n[互動資料流圖](dataflow.html)',source,flags=re.S)
    md=markdown.Markdown(extensions=['tables','fenced_code','toc','attr_list'],extension_configs={'toc':{'toc_depth':'2-3'}})
    body=md.convert(source)
    body=re.sub(r'href="(user-manual|handoff|code-review)\.md',r'href="\1.html',body)
    body=re.sub(r'<p><img([^>]+)alt="([^"]*)"([^>]*)></p>',lambda m:'<figure><img'+m[1]+'alt="'+m[2]+'"'+m[3]+'><figcaption>'+m[2]+'</figcaption></figure>',body)
    title=source.splitlines()[0].removeprefix('# ')
    document=f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><header><p>詠翔專案工作台 · 2026-10-03 · 文件與程式版本分開核對</p><nav><a href="index.html">文件入口</a><a href="user-manual.html">使用說明</a><a href="handoff.html">系統交接</a><a href="code-review.html">審查報告</a><a href="dataflow.html">資料流圖</a><button class="print" onclick="window.print()">列印／另存 PDF</button></nav></header><main><aside aria-label="本頁目錄">{md.toc}</aside><article><p class="frontnote">程式審查基準 e66c626｜示範截圖非正式驗收｜本輪未部署業務修正</p>{body}</article></main><footer>維護來源：docs/guide/{name}.md。圖片為本機隔離示範；公司私有快照及憑證未包含於文件。</footer></body></html>'''
    (DEST/(name+'.html')).write_text(document,encoding='utf-8')
    return title

def main():
    DEST.mkdir(exist_ok=True,parents=True)
    names=('user-manual','handoff','code-review')
    titles={name:render(name) for name in names}
    links=''.join(f'<h2><a href="{name}.html">{html.escape(title)}</a></h2><p><a href="{name}.md">Markdown 原稿</a> · <a href="{name}.pdf">PDF 版</a></p>' for name,title in titles.items())
    (DEST/'index.html').write_text(f'<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>詠翔工作台圖文文件</title><style>{CSS}</style><body><header><p>詠翔工作台 · 圖文文件</p></header><main style="display:block;max-width:1000px"><article><h1>使用、交接與審查</h1><p>2026-10-03｜先依閱讀目的選擇文件。可離線閱讀，也可列印成 PDF。</p>{links}<h2><a href="dataflow.html">互動資料流圖</a></h2><p>從 Lark 來源、工作台操作，到資料庫、Drive 與專用登錄目的地。圖文為繁體中文，圖檢視器控制介面為英文。</p><img src="assets/dataflow.png" alt="資料從哪裡來、到哪裡去"><p>Code Review 發現尚待修復，文件完成不代表正式驗收或部署完成。</p></article></main></body></html>',encoding='utf-8')
    print('Built 3 guides and index.')

if __name__=='__main__':main()
