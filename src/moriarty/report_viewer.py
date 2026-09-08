from __future__ import annotations
import argparse,html,json,webbrowser
from pathlib import Path
from typing import Any

GROUPS={
 "social":{"facebook","whatsapp","telegram","syncme","truecaller","reddit"},
 "profiles":{"facebook","whatsapp","telegram","syncme","truecaller"},
 "identity":{"local","truecaller","syncme","telegram"},
 "reputation":{"reputation","ftc"},
 "breaches":{"cybernews","databreach","hudsonrock","pastebin","breachdirectory","localbreach","ahmia"},
 "web":{"github","reddit","brave","duckduckgo","web-mentions","whatsmyname","wayback","commoncrawl"},
 "documents":{"documents"},"business":{"business","opensanctions","btk","disposable"},
}
def flatten(value:Any,prefix="",depth=0):
 rows=[]
 if depth>5:return rows
 if isinstance(value,dict):
  for key,item in value.items():
   label=f"{prefix}.{key}" if prefix else str(key)
   if isinstance(item,(dict,list,tuple)):rows.extend(flatten(item,label,depth+1))
   elif item not in (None,""):rows.append((label.replace("_"," "),str(item)))
 elif isinstance(value,(list,tuple)):
  for index,item in enumerate(value[:200],1):
   label=f"{prefix} #{index}"
   if isinstance(item,(dict,list,tuple)):rows.extend(flatten(item,label,depth+1))
   elif item not in (None,""):rows.append((label,str(item)))
 return rows
def is_username(data):return "username" in data and isinstance(data.get("findings"),dict)
def render(data,category="all"):
 print(f"\nGÖKBÖRÜ INTELLIGENCE · {category.upper()} OUTPUT\n"+"═"*76)
 if is_username(data):
  findings=data.get("findings",{})
  if category in {"all","profiles","social","web"}:
   profiles=findings.get("profiles",[]);print(f"\nPROFILES ({len(profiles)})\n"+"─"*76)
   for index,item in enumerate(profiles[:200],1):
    print(f"[{index:03}] {item.get('name') or item.get('username') or 'Profile'} · {item.get('status','unverified')} · {round(float(item.get('confidence') or 0)*100)}%")
    print(f"      {item.get('url') or item.get('web_url') or item.get('canonical_url') or '—'}")
    if item.get("bio"):print(f"      Bio: {item['bio']}")
    if item.get("avatar_url"):print(f"      Image: {item['avatar_url']}")
    print(f"      Evidence: {', '.join(map(str,item.get('evidence_sources',[]))) or '—'}")
  if category in {"all","breaches"}:
   breaches=findings.get("breaches",[]);print(f"\nBREACH RECORDS ({len(breaches)})\n"+"─"*76)
   for index,item in enumerate(breaches[:200],1):
    print(f"[{index:03}] {item.get('source','breach')} · risk={item.get('risk','unknown')} · matches={item.get('match_count',len(item.get('records',[])))}")
    print(f"      Sources: {', '.join(map(str,item.get('breach_sources',[]))) or '—'}")
    print(f"      Fields: {', '.join(map(str,item.get('exposed_fields',[]))) or '—'}")
  if category in {"all","history"}:
   history=findings.get("historical",[]);print(f"\nHISTORICAL ({len(history)})\n"+"─"*76)
   for index,item in enumerate(history[:200],1):print(f"[{index:03}] {item.get('archive') or item.get('source')} · {item.get('captured_at','—')}\n      {item.get('original_url') or item.get('url') or '—'}")
  return
 sources=data.get("sources",[])
 if category=="errors":chosen=[x for x in sources if x.get("error") or x.get("state") in {"failed","blocked"}]
 elif category=="all":chosen=sources
 else:chosen=[x for x in sources if x.get("source") in GROUPS.get(category,set())]
 print(f"TARGET: {data.get('number','—')} · RECORDS: {len(chosen)}\n")
 for index,item in enumerate(chosen,1):
  print(f"┌─ [{index:02}] {str(item.get('source','source')).upper()} · {item.get('provider_status') or item.get('state') or '—'}")
  if item.get("error"):print(f"│  ERROR: {item['error']}")
  rows=flatten(item.get("data"))
  if not rows:print("│  No structured data returned.")
  for key,value in rows[:120]:print(f"│  {key[:28]:<28} {value[:500]}")
  if len(rows)>120:print(f"│  ... {len(rows)-120} additional fields")
  print("└"+"─"*74)
def gallery(data,path:Path):
 profiles=list(data.get("findings",{}).get("profiles",[]));cards=[]
 if not is_username(data):
  for source in data.get("sources",[]):
   if source.get("source") not in GROUPS["profiles"]:continue
   flat=dict(flatten(source.get("data")))
   def first(*names):
    for key,value in flat.items():
     if any(name in key.lower() for name in names) and value:return value
    return ""
   profiles.append({"name":first("display name","name","caller") or source.get("source","Profile"),"username":first("username","handle"),"url":first("profile url","web url","url"),"avatar_url":first("avatar","photo","image"),"status":source.get("provider_status") or source.get("state") or "found","confidence":1 if source.get("finding")=="finding" else 0})
 for item in profiles:
  url=item.get("url") or item.get("web_url") or item.get("canonical_url") or "#";avatar=item.get("avatar_url") or "";name=item.get("name") or item.get("title") or item.get("username") or "Profile"
  image=f'<img src="{html.escape(str(avatar),quote=True)}" alt="">' if avatar else '<div class="placeholder">@</div>'
  cards.append(f'<article>{image}<div><h2>{html.escape(str(name))}</h2><p>{html.escape(str(item.get("status","unverified")))} · {round(float(item.get("confidence") or 0)*100)}%</p><a href="{html.escape(str(url),quote=True)}">{html.escape(str(url))}</a><p>{html.escape(str(item.get("bio", "")))}</p></div></article>')
 if not cards:cards.append('<article><div class="placeholder">?</div><div><h2>No profile cards</h2><p>The selected providers returned no usable profile or image fields.</p></div></article>')
 target=path.with_suffix(".profiles.html");target.write_text('<!doctype html><meta charset="utf-8"><title>Gökbörü Profiles</title><style>body{background:#070b11;color:#e7eef5;font:15px system-ui;margin:32px}h1{color:#ef3650}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px}article{display:flex;gap:15px;background:#111923;border:1px solid #293848;border-radius:12px;padding:16px}img,.placeholder{width:76px;height:76px;border-radius:12px;object-fit:cover;background:#202b38;display:grid;place-items:center;font-size:30px}h2{margin:0 0 6px}p{color:#9db0c0}a{color:#55b9eb;overflow-wrap:anywhere}</style><h1>GÖKBÖRÜ · Profile Intelligence</h1><div class="grid">'+''.join(cards)+'</div>',encoding="utf-8");webbrowser.open(target.resolve().as_uri());print(target.resolve())
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument("report");p.add_argument("category",nargs="?",default="all");p.add_argument("--gallery",action="store_true");a=p.parse_args(argv);path=Path(a.report).expanduser();data=json.loads(path.read_text(encoding="utf-8"));gallery(data,path) if a.gallery else render(data,a.category)
if __name__=="__main__":main()
