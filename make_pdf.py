import re,sys,os
BASE="https://psinglap.github.io/websearch-api-eval/"
OUT=sys.argv[1]; os.makedirs(OUT+"/memo",exist_ok=True)
CSS='''<style media="print">
@page{size:A4;margin:12mm 11mm}
body{font-size:12.5px;line-height:1.5}
.hero{padding:0 0 8px!important}.hero .card{margin-top:10px;padding:14px 18px!important}
.card .big{font-size:24px!important;margin:8px 0!important}.card .stats b{font-size:20px!important}
h1{font-size:28px!important;margin:10px 0!important}.dek{font-size:15px!important;margin:0 0 12px!important}
h2{font-size:21px!important;margin:14px 0 8px!important}h3{font-size:16px!important;margin:16px 0 6px!important}
h4,h4.sub{margin:14px 0 6px!important}
.part{margin-top:22px!important}.uc,.agent{margin-top:14px!important}.agent{padding:10px 14px!important;margin-bottom:8px!important}
p{margin:6px 0}ul,ol{margin:6px 0}
figure{margin:8px 0 10px!important;padding:8px!important}figure img{max-height:235mm;width:auto!important;max-width:100%;margin:0 auto}
.tw{margin:8px 0 12px!important}
table.q{table-layout:fixed}table.q th,table.q td{font-size:9.5px;padding:5px 6px;white-space:normal;overflow-wrap:anywhere}
table.q code{font-size:9px;padding:0 3px;white-space:normal;word-break:break-word}
.fold{display:flex;justify-content:space-between;align-items:center;border:1px solid var(--line);border-radius:10px;padding:10px 16px;margin:8px 0;text-decoration:none;color:var(--fg);font:500 15px "Inter Tight",sans-serif}
.fold span{font:500 11px "IBM Plex Mono",monospace;color:var(--accent);text-transform:uppercase;letter-spacing:.06em}
.dd{break-before:auto;margin-top:22px}.dd:first-of-type{break-before:page}.dd h3{margin-top:0!important;padding-bottom:6px;border-bottom:1px solid var(--line)}
.dd+.dd{break-before:auto;margin-top:22px}.dd:first-of-type{break-before:page}
.backlink{display:inline-block;margin-top:8px;font-size:11.5px}
</style>'''
MEMO_CSS='''<style media="print">
body{font-size:12px}
.hero{padding:0 0 4px!important}
.eyebrow{font-size:10.5px}
h1{font-size:24px!important;margin:6px 0 4px!important}
.dek{font-size:13px!important;margin:0 0 6px!important}
.author{font-size:12.5px}.author i{width:22px;height:22px}
.memo-meta{margin-top:8px!important;padding:8px 12px!important;font-size:12.5px!important}
.hero .card{margin-top:8px!important;padding:10px 16px!important}
.card .big{display:none}.card>.eyebrow{margin-bottom:6px}
.card .stats{padding-top:6px!important;border-top:0!important}.card .stats b{font-size:18px!important}
article h2{margin-top:12px!important}
ol{margin:4px 0}ol li{margin:2px 0!important}
figure img{max-height:110mm}figure img[src*="query_grid"]{max-height:none;width:100%!important}
</style>'''
COLS='<colgroup><col style="width:4%"><col style="width:14%"><col style="width:14%"><col style="width:12%"><col style="width:13%"><col style="width:7%"><col style="width:23%"><col style="width:13%"></colgroup>'
def absl(s,depth):
    pre=BASE if depth==0 else BASE+"memo/"
    s=re.sub(r'href="(?!https?:|#|mailto:)([^"]*)"',lambda m:'href="%s"'%(BASE+m.group(1) if depth==0 else (BASE+m.group(1)[3:] if m.group(1).startswith("../") else BASE+"memo/"+m.group(1))),s)
    return s
def prep(src,dst,depth):
    s=open(src).read()
    imgdir=os.path.abspath("img")
    s=s.replace('src="img/','src="file://%s/'%imgdir).replace('src="../img/','src="file://%s/'%imgdir)
    s=absl(s,depth)
    s=s.replace("</head>",CSS+(MEMO_CSS if depth==1 else "")+"</head>",1)
    # query tables: 8 columns with Answer key
    s=re.sub(r'<table>(\s*<thead>\s*<tr>\s*<th>QID</th>(?:(?!</thead>).)*Answer key)',lambda m:'<table class="q">'+COLS+m.group(1),s,flags=re.S)
    # deep dives -> fold links + appendix sections
    dd=re.findall(r'<details class="faq"[^>]*><summary>(.*?)</summary><div class="faqb">(.*?)</div></details>',s,flags=re.S)
    if dd:
        links="".join('<a class="fold" href="#dd-%d">%s<span>Open section &#8595;</span></a>'%(i,t) for i,(t,b) in enumerate(dd,1))
        apx="".join('<section class="dd" id="dd-%d"><h3>%s</h3>%s<a class="backlink" href="#deep">&#8593; Back to Details and deep dives</a></section>'%(i,t,b) for i,(t,b) in enumerate(dd,1))
        s=re.sub(r'<details class="faq".*</details>',links,s,count=1,flags=re.S)
        s=s.replace("</article>",apx+"</article>",1)
        s=s.replace('<p class="muted">Open any section to read the full data.</p>','<p class="muted">Click a section to jump to its full data; each ends with a link back here.</p>')
    open(dst,"w").write(s)
prep("index.html",OUT+"/index.html",0); prep("memo/index.html",OUT+"/memo/index.html",1); print("ok")
