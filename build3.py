import re, html, markdown, sys
L=open(sys.argv[1],encoding="utf-8").read().split("\n")
def seg(a,b): return "\n".join(L[a-1:b])
def find(prefix,start=1):
    for i in range(start-1,len(L)):
        if L[i].startswith(prefix): return i+1
    raise SystemExit("marker not found: "+prefix)
iKey=find("### Key metrics by all three"); iG=find("**GTM Agent**"); iI=find("**I",iG+1); iF=find("**Finance agent**")
iPQ=find("### **Per query"); iGQ=find("**GTM ",iPQ); iIQ=find("**Insurance ",iGQ+1); iFQ=find("**Finance takeaway")
iSF=find("**Setup & friction"); iDD=find("**Details and Deep-dives"); iFL=find("### Detailed Timed"); iHJ=find("### How each result")
iGD=find("### GTM agent queries"); iID=find("### Insurance agent queries"); iFD=find("### Finance agent"); iSrc=find("### Sources")
iSum=next(i+1 for i in range(len(L)) if re.match(r"^\*{1,3}S\*\*u",L[i]) or L[i].startswith("*M**y**"))
P={"dek":L[4].lstrip("# ").strip(),"intro":seg(6,iSum-1),"analysis":seg(iSum+1,iKey-1),
   "gA":seg(iG,iI-1),"iA":seg(iI,iF-1),"fA":seg(iF,iPQ-1),"gQ":seg(iGQ,iIQ-1),"iQ":seg(iIQ,iFQ-1),"fQ":seg(iFQ,iSF-1),
   "fric":seg(iSF+1,iDD-1),"flog":seg(iFL+1,iHJ-1),"judge":seg(iHJ+1,iGD-1),"gD":seg(iGD+1,iID-1),"iD":seg(iID+1,iFD-1),"fD":seg(iFD+1,iSrc-1)}
IMG={"Overall scorecard":"overall_scorecard.png","GTM key metrics":"gtm_key_metrics.png","Insurance key metrics":"insurance_key_metrics.png",
     "Finance key metrics":"finance_key_metrics.png","GTM per-query grid":"gtm_query_grid.png","Insurance per-query grid":"insurance_query_grid.png",
     "Finance per-query grid":"finance_query_grid.png","Time and steps":"time_steps_activation.png","What stands between":"activation_gates.png"}
def fig(alt):
    f=next(v for k,v in IMG.items() if alt.startswith(k))
    return f'\n\n<figure><a href="img/{f}" target="_blank" rel="noopener"><img src="img/{f}" alt="{html.escape(alt)}" loading="lazy"></a><figcaption>{html.escape(alt)} · click to enlarge</figcaption></figure>\n\n'
def clean(s):
    s=s.replace("\\~","~").replace("\\&","&").replace("&#91;","[").replace("&#32;"," ").replace("\\]","]")
    s=re.sub(r"\*\*\[image: ([^\]]+)\]([^\n]*?)\*\*",lambda m: fig(m.group(1))+("**"+m.group(2).strip()+"**" if m.group(2).strip() else ""),s)
    s=re.sub(r"(?<!\*)\*?\[image: ([^\]]+)\](?:\*(?!\*))?",lambda m: fig(m.group(1)),s)
    while "****" in s: s=s.replace("****","")
    return s
def clip_cols(h):
    def tbl(m):
        t=m.group(0); heads=re.findall(r"<th[^>]*>(.*?)</th>",t,re.S)
        idx=[i for i,x in enumerate(heads) if re.search(r"Answer key|Source",x)]
        if not idx: return t
        def row(rm):
            cells=re.findall(r"<td[^>]*>.*?</td>",rm.group(0),re.S)
            for i in idx:
                if i<len(cells):
                    inner=re.sub(r"^<td[^>]*>|</td>$","",cells[i]); txt=html.escape(re.sub(r"<[^>]+>","",inner),quote=True)
                    cells[i]=f'<td class="clipcell"><div class="clip" title="{txt}">{inner}</div></td>'
            return "<tr>"+"".join(cells)+"</tr>"
        return re.sub(r"<tr>(?:(?!</tr>).)*<td.*?</tr>",row,t,flags=re.S)
    return re.sub(r"<table>.*?</table>",tbl,h,flags=re.S)
def md(s):
    h=markdown.markdown(clean(s),extensions=["tables","sane_lists"])
    h=clip_cols(h)
    return h.replace("<table>",'<div class="tw"><table>').replace("</table>","</table></div>")
def split_lead(s):
    c=clean(s); first,_,rest=c.partition("\n")
    first=re.sub(r"\*\*","",first); label,_,desc=first.partition(":")
    return desc.strip(), rest
def strip_label(s):  # remove "**GTM Queries:**" style label
    c=clean(s); return re.sub(r"^\*\*[^*]*?(Queries|takeaway)[^*]*?\*\*\s*","",c,count=1)
AG=[("gtm","GTM agent","#6c4cf1","gA","gQ","gD"),("insurance","Insurance agent","#0f8a7e","iA","iQ","iD"),("finance","Finance agent","#c2410c","fA","fQ","fD")]
def badge(i,sid,name,col,sub,anchor):
    return f'<div class="agent" id="{anchor}" style="--c:{col}"><span class="num">{i}</span><div><div class="an">{name}</div><div class="as">{html.escape(sub)}</div></div></div>'
key=[];pq=[]
for i,(sid,name,col,a,q,d) in enumerate(AG,1):
    desc,rest=split_lead(P[a]); key.append(badge(i,sid,name,col,desc,sid)+md(rest))
    pq.append(badge(i,sid,name+" · per question",col,"What each API returned for the "+name.split()[0]+" queries","%s-perq"%sid)+md(strip_label(P[q])))
ACC_N=[0]
def acc(q,body,open_=False):
    ACC_N[0]+=1; return f'<details class="faq" id="dd-{ACC_N[0]}"{" open" if open_ else ""}><summary>{q}</summary><div class="faqb">{body}</div></details>'
deep="".join([acc("Detailed timed setup and friction log",md(P["flog"])),acc("How each result was judged",md(P["judge"])),
  acc("GTM agent: queries, what each API returned and metric scorecard",md(P["gD"])),
  acc("Insurance agent: queries, what each API returned and metric scorecard",md(P["iD"])),
  acc("Finance agent (Rogo-style): queries, what each API returned and metric scorecard",md(P["fD"]))])
tpl=open(sys.argv[2],encoding="utf-8").read()
for k,v in {"{{DEK}}":html.escape(P["dek"]),"{{INTRO}}":md(P["intro"]),"{{ANALYSIS}}":md(P["analysis"]),"{{KEY}}":"".join(key),
            "{{PQ}}":"".join(pq),"{{FRIC}}":md(P["fric"]),"{{DEEP}}":deep}.items(): tpl=tpl.replace(k,v)
open(sys.argv[3],"w",encoding="utf-8").write(tpl); print("ok")
