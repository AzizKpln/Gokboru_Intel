from __future__ import annotations
import asyncio,json,os,shutil,sys
from datetime import datetime
from pathlib import Path
from textual import on
from textual.app import App,ComposeResult
from textual.containers import Horizontal,Vertical,VerticalScroll
from textual.widgets import Button,Checkbox,DataTable,Footer,Input,Label,Log,Select,Static,Tab,TabbedContent,TabPane
from moriarty.services.username_audit import DEFAULT_USERNAME_SOURCES,compact_username_audit

PHONE=(("local","Number & line"),("truecaller","Truecaller"),("syncme","Sync.me"),("telegram","Telegram"),("facebook","Facebook"),("whatsapp","WhatsApp"),("cybernews","Cybernews"),("databreach","DataBreach"),("hudsonrock","Hudson Rock"),("github","GitHub"),("reddit","Reddit"),("brave","Brave Search"),("duckduckgo","DuckDuckGo"),("web-mentions","Web mentions"),("pastebin","Pastebin"),("documents","PDF & documents"),("reputation","Comments & reputation"),("business","Business listings"),("disposable","Temporary SMS"),("opensanctions","OpenSanctions"),("ftc","FTC complaints"),("btk","BTK portability"))
USER=tuple((s.name,s.name.replace("_"," ").title()) for s in DEFAULT_USERNAME_SOURCES)
PP={"quick":{"local","reputation","business","disposable"},"social":{"local","truecaller","syncme","telegram","facebook","whatsapp"},"leaks":{"local","cybernews","databreach","hudsonrock","pastebin"},"web":{"local","github","brave","duckduckgo","web-mentions","documents"},"all":{k for k,_ in PHONE}}
UP={"quick":{"github","gitlab","whatsmyname","socialscan"},"social":{s.name for s in DEFAULT_USERNAME_SOURCES if "social" in s.category or s.name in {"reddit","telegram","bluesky"}},"leaks":{s.name for s in DEFAULT_USERNAME_SOURCES if s.category in {"breach_exposure","darkweb_index"}},"web":{s.name for s in DEFAULT_USERNAME_SOURCES if s.category not in {"breach_exposure","darkweb_index","federated_profiles"}},"all":{s.name for s in DEFAULT_USERNAME_SOURCES}}
TR={"sources":"KAYNAK MATRİSİ","target":"ARAŞTIRMA HEDEFİ","quick":"HIZLI","social":"SOSYAL","leaks":"SIZINTI","web":"AÇIK WEB","all":"TÜMÜ","run":"ARAŞTIRMAYI BAŞLAT","stop":"DURDUR","overview":"Özet","findings":"Bulgular","breaches":"İhlâller","source_tab":"Kaynaklar","activity":"Canlı günlük","ready":"Hazır","running":"Araştırma çalışıyor","done":"Araştırma tamamlandı","failed":"Araştırma başarısız","need":"Hedef, yetki onayı ve en az bir kaynak gerekli.","phone_consent":"Bu numara için sorgulama yetkim var","user_consent":"Bu kullanıcı adı için sorgulama yetkim var","selected":"SEÇİLİ","expand":"SONUÇLARI BÜYÜT","back":"KOMUTA DÖN"}
EN={"sources":"SOURCE MATRIX","target":"INVESTIGATION TARGET","quick":"QUICK","social":"SOCIAL","leaks":"EXPOSURE","web":"OPEN WEB","all":"ALL","run":"START INVESTIGATION","stop":"STOP","overview":"Overview","findings":"Findings","breaches":"Breaches","source_tab":"Sources","activity":"Live activity","ready":"Ready","running":"Investigation running","done":"Investigation complete","failed":"Investigation failed","need":"A target, authorization and at least one source are required.","phone_consent":"I am authorized to query this number","user_consent":"I am authorized to query this username","selected":"SELECTED","expand":"EXPAND RESULTS","back":"BACK TO COMMAND"}

class GokboruApp(App):
 TITLE="Gökbörü Intelligence";SUB_TITLE="Analyst Operations Console"
 CSS="""
 Screen{background:#06090e;color:#d7e1e9}#header{height:5;background:#0a0f16;border-bottom:solid #762633;padding:1 2}#brand{width:1fr;padding:1 0;color:#edf3f7;text-style:bold}#target-modes{width:42;height:3}#target-modes Button{width:21;height:3;border:none;background:#0e1721;color:#718a9e}#target-modes Button.active-mode{background:#28161c;color:white;border-bottom:solid #e13950;text-style:bold}#engine{width:25;text-align:right;padding:1 0;color:#42d39c}
 #workspace{height:1fr}#sidebar{width:34;background:#090e15;border-right:solid #1e2a35;padding:1}#source-head{height:3}#source-title{width:1fr;padding:1 0;color:#e2465b;text-style:bold}#source-count{width:13;text-align:right;padding:1 0;color:#44d19a}#preset-a,#preset-b{height:3}#preset-a Button,#preset-b Button{width:1fr;height:3;margin-right:1;border:none;background:transparent;color:#6d879a}#preset-a Button:hover,#preset-b Button:hover{background:#111c26;color:#e3edf3}#source-list{height:1fr;margin-top:1;scrollbar-color:#354858 #111821}.source{width:100%;height:2;border:none;background:transparent;color:#8ca2b3;padding:0 1}.source:hover,.source:focus{background:#111b25;color:#e7eff4}.source.-on{background:#10201c;color:#daf4e9;border-left:tall #39ce97}#identity{height:3;color:#3f5668;padding:0 1}
 #main{width:1fr;background:#06090e;padding:1 2}#command{height:11;background:#0a1017;border:solid #202d39;padding:1 2}#command-head{height:2}#command-title{width:23;color:#e2465b;text-style:bold}#command-context{width:1fr;color:#60798d}#target-row,#option-row{height:3}#target-row Input,#target-row Select,#option-row Input{background:#0e151e;border:none;color:#dce6ed;margin-right:1}#target{width:1fr}#region{width:17}#timeout{width:10}#authorization{width:35;height:3;border:none;background:transparent;color:#71c7a7}#report{width:1fr}
 #controls{height:3;margin:1 0}#run{width:24;height:3;background:#a52135;border:solid #ce344b;color:white;text-style:bold}#run:hover{background:#c12a41}#stop{width:10;height:3;margin-left:1;background:#171116;border:solid #3e2831;color:#786c71}#expand{width:17;height:3;margin-left:1;background:#101a24;border:solid #294052;color:#79a9c5}#status{width:1fr;padding:1;color:#718da1}#language{width:8;height:3;border:none;background:transparent;color:#7795aa}#results-label{height:2;color:#718798;text-style:bold}#results{height:1fr;background:#080d13;border:solid #202c37}TabbedContent{height:1fr}TabPane{padding:0}ContentSwitcher{background:#080d13}Tabs{height:3;background:#0b131b;color:#61788b}Tab{padding:0 2}Tab.-active{background:#14212d;color:#eef4f7;text-style:bold}Underline{color:#df354c}#overview{height:1fr;padding:2 3;color:#c8d4dd}#findings,#breaches,#activity-log{height:1fr;background:#080d13;padding:1 2}#source-table{height:1fr;background:#080d13;color:#afd0e2}#main.expanded #command{display:none}Footer{height:1;background:#070b10;color:#5f7688}
 """
 BINDINGS=[("ctrl+r","run_investigation","Run"),("ctrl+l","toggle_language","TR/EN"),("ctrl+a","select_all","All"),("escape","stop","Stop"),("q","quit","Quit")]
 def __init__(self):super().__init__();self.lang="en";self.mode="phone";self.process=None;self.source_data={}
 @property
 def text(self):return TR if self.lang=="tr" else EN
 def compose(self)->ComposeResult:
  with Horizontal(id="header"):
   yield Static("[bold #e43a51]GÖKBÖRÜ[/]  [bold #58aee0]INTELLIGENCE[/]   [dim]// OPERATIONS CONSOLE[/]",id="brand")
   with Horizontal(id="target-modes"):yield Button("PHONE INTEL",id="mode-phone",classes="active-mode");yield Button("USERNAME INTEL",id="mode-username")
   yield Static("[bold #42d39c]● ENGINE ONLINE[/]",id="engine")
  with Horizontal(id="workspace"):
   with Vertical(id="sidebar"):
    with Horizontal(id="source-head"):yield Label("SOURCE MATRIX",id="source-title");yield Static("● 4 SELECTED",id="source-count")
    with Horizontal(id="preset-a"):yield Button("QUICK",id="quick");yield Button("SOCIAL",id="social");yield Button("EXPOSURE",id="leaks")
    with Horizontal(id="preset-b"):yield Button("OPEN WEB",id="web");yield Button("ALL",id="all")
    with VerticalScroll(id="source-list"):
     for k,l in PHONE:yield Checkbox(l,id=f"phone-{k}",classes="source phone-source")
     for k,l in USER:yield Checkbox(l,id=f"username-{k}",classes="source username-source")
    yield Static("Gökbörü Intelligence\nAzizKpln@protonmail.com",id="identity")
   with Vertical(id="main"):
    with Vertical(id="command"):
     with Horizontal(id="command-head"):yield Label("INVESTIGATION TARGET",id="command-title");yield Static("PHONE INTELLIGENCE · SOCIAL · BREACH · OPEN WEB",id="command-context")
     with Horizontal(id="target-row"):yield Input(placeholder="+90 5xx xxx xx xx",id="target");yield Select((("TR +90","TR"),("US +1","US"),("GB +44","GB"),("AUTO","")),value="TR",id="region");yield Input(value="180",placeholder="SEC",id="timeout")
     with Horizontal(id="option-row"):yield Checkbox("I am authorized to query this number",id="authorization");yield Input(value=f"reports/gokboru-{datetime.now():%Y%m%d-%H%M%S}.json",id="report")
    with Horizontal(id="controls"):yield Button("START INVESTIGATION",id="run");yield Button("STOP",id="stop",disabled=True);yield Button("EXPAND RESULTS",id="expand",disabled=True);yield Static("Ready",id="status");yield Button("TR",id="language")
    yield Label("INVESTIGATION OUTPUTS",id="results-label")
    with TabbedContent(id="results"):
     with TabPane("Overview",id="tab-overview"):yield Static("[dim]Enter a target, select sources, and start the investigation.[/]",id="overview")
     with TabPane("Findings",id="tab-findings"):yield Log(id="findings",highlight=True)
     with TabPane("Breaches",id="tab-breaches"):yield Log(id="breaches",highlight=True)
     with TabPane("Sources",id="tab-sources"):yield DataTable(id="source-table",zebra_stripes=True)
     with TabPane("Live activity",id="tab-activity"):yield Log(id="activity-log",highlight=True)
  yield Footer()
 def on_mount(self):
  for w in self.query(".username-source"):w.display=False
  self.apply_preset("quick");self.reset_table()
 def config(self):
  try:
   d=json.loads((Path.home()/".local/share/moriarty-v5/gokboru/configuration.json").read_text(encoding="utf-8"));return d if isinstance(d,dict) else {}
  except (OSError,json.JSONDecodeError):return {}
 def choices(self):return USER if self.mode=="username" else PHONE
 def box(self,k):return self.query_one(f"#{self.mode}-{k}",Checkbox)
 def selected(self):return [k for k,_ in self.choices() if self.box(k).value]
 def count(self):self.query_one("#source-count",Static).update(f"● {len(self.selected())} {self.text['selected']}")
 def apply_preset(self,name):
  values=set((UP if self.mode=="username" else PP)[name])
  if self.mode=="username" and name=="leaks":
   values.discard("localbreach");c=self.config()
   if not(c.get("breachdirectory_api_key") or os.getenv("BREACHDIRECTORY_API_KEY") or os.getenv("RAPIDAPI_KEY")):values.discard("breachdirectory")
  for k,_ in self.choices():self.box(k).value=k in values
  self.count()
 def set_mode(self,mode):
  self.mode=mode;u=mode=="username";self.query_one("#mode-phone",Button).set_class(not u,"active-mode");self.query_one("#mode-username",Button).set_class(u,"active-mode")
  for w in self.query(".phone-source"):w.display=not u
  for w in self.query(".username-source"):w.display=u
  self.query_one("#region",Select).display=not u;self.query_one("#target",Input).value="";self.query_one("#target",Input).placeholder="Kullanıcı adı / Username" if u else "+90 5xx xxx xx xx";self.query_one("#authorization",Checkbox).value=False;self.query_one("#authorization",Checkbox).label=self.text["user_consent" if u else "phone_consent"];self.query_one("#command-context",Static).update("USERNAME INTELLIGENCE · PROFILES · BREACHES · HISTORY" if u else "PHONE INTELLIGENCE · SOCIAL · BREACH · OPEN WEB");self.query_one("#source-title",Label).update("USERNAME SOURCES" if u else self.text["sources"]);self.apply_preset("quick")
 @on(Button.Pressed)
 def pressed(self,e):
  i=e.button.id
  if i=="mode-phone":self.set_mode("phone")
  elif i=="mode-username":self.set_mode("username")
  elif i in PP:self.apply_preset(i)
  elif i=="run":self.run_worker(self.execute(),exclusive=True)
  elif i=="stop":self.action_stop()
  elif i=="expand":self.toggle_results()
  elif i=="language":self.action_toggle_language()
 @on(Checkbox.Changed)
 def changed(self,e):
  if e.checkbox.id and e.checkbox.id.startswith(("phone-","username-")):self.count()
 def action_select_all(self):self.apply_preset("all")
 def action_run_investigation(self):self.run_worker(self.execute(),exclusive=True)
 def action_stop(self):
  if self.process and self.process.returncode is None:self.process.terminate()
 def action_toggle_language(self):
  self.lang="en" if self.lang=="tr" else "tr";t=self.text
  for i,k in (("quick","quick"),("social","social"),("leaks","leaks"),("web","web"),("all","all"),("run","run"),("stop","stop")):self.query_one(f"#{i}",Button).label=t[k]
  self.query_one("#source-title",Label).update("USERNAME SOURCES" if self.mode=="username" else t["sources"]);self.query_one("#command-title",Label).update(t["target"]);self.query_one("#authorization",Checkbox).label=t["user_consent" if self.mode=="username" else "phone_consent"];self.query_one("#language",Button).label="TR" if self.lang=="en" else "EN";self.query_one("#expand",Button).label=t["back"] if self.query_one("#main").has_class("expanded") else t["expand"];self.count()
  for tab,label in zip(self.query("#results Tab"),(t["overview"],t["findings"],t["breaches"],t["source_tab"],t["activity"])):
   if isinstance(tab,Tab):tab.label=label
 def toggle_results(self):
  m=self.query_one("#main");m.toggle_class("expanded");self.query_one("#expand",Button).label=self.text["back"] if m.has_class("expanded") else self.text["expand"]
 async def execute(self):
  target=self.query_one("#target",Input).value.strip();selected=self.selected()
  if not target or not self.query_one("#authorization",Checkbox).value or not selected:self.notify(self.text["need"],severity="error");return
  timeout=self.query_one("#timeout",Input).value or "180";report=Path(self.query_one("#report",Input).value).expanduser();log=self.query_one("#activity-log",Log);log.clear();log.write_line(f"▶ {self.text['running']}: {target}")
  if self.mode=="username":cmd=[sys.executable,"-m","moriarty","username-audit",target,"--sources",",".join(selected),"--timeout",timeout,"--wmn-limit","180","--exposure-limit","20","--full-json"]
  else:
   cmd=[sys.executable,"-m","moriarty.web_phone_audit_entry",target,"--sources",",".join(selected),"--timeout",timeout,"--i-own-this-number"];region=str(self.query_one("#region",Select).value or "")
   if region:cmd += ["--region",region]
   if "telegram" in selected:cmd += ["--telegram-account",target]
   if os.name!="nt" and shutil.which("xvfb-run"):cmd=[shutil.which("xvfb-run"),"-a"]+cmd
  env=os.environ.copy();c=self.config()
  if c.get("breachdirectory_api_key"):env.setdefault("BREACHDIRECTORY_API_KEY",str(c["breachdirectory_api_key"]))
  if c.get("github_token"):env.setdefault("GITHUB_TOKEN",str(c["github_token"]))
  self.query_one("#run",Button).disabled=True;self.query_one("#stop",Button).disabled=False;self.query_one("#status",Static).update(self.text["running"]);self.process=await asyncio.create_subprocess_exec(*cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env);out,err=await self.process.communicate();self.query_one("#run",Button).disabled=False;self.query_one("#stop",Button).disabled=True
  if self.process.returncode:log.write_line((err or out).decode(errors="replace"));self.query_one("#status",Static).update(self.text["failed"]);self.notify(self.text["failed"],severity="error");return
  try:raw=json.loads(out.decode())
  except Exception:log.write_line(out.decode(errors="replace"));self.notify(self.text["failed"],severity="error");return
  data=compact_username_audit(raw) if self.mode=="username" else raw;report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  if self.mode=="username":self.render_username(raw,data,report)
  else:self.render_phone(raw,report)
  self.query_one("#status",Static).update(self.text["done"]);self.query_one("#expand",Button).disabled=False;log.write_line(f"✓ {self.text['done']}");self.notify(self.text["done"])
 def reset_table(self):
  t=self.query_one("#source-table",DataTable);t.clear(columns=True);t.add_columns("Source","State","Provider","Duration")
 def source_table(self,sources,user=False):
  self.reset_table();t=self.query_one("#source-table",DataTable);self.source_data={}
  for x in sources:
   n=str(x.get("source","—"));self.source_data[n]=x;t.add_row(n,str((x.get("verification_status") if user else x.get("state")) or "—"),str((x.get("display_status") if user else x.get("provider_status")) or "—"),f"{int(x.get('duration_ms',0) or 0)/1000:.1f}s",key=n)
 def render_phone(self,d,report):
  s=d.get("summary",{});self.query_one("#overview",Static).update(f"[bold]PHONE INVESTIGATION[/]\n\nTarget       [bold]{d.get('number','—')}[/]\nSources      {s.get('completed',0)} / {s.get('requested',0)}\nFindings     [bold #e6465c]{s.get('findings',0)}[/]\nClear        [bold #42d39c]{s.get('clear',0)}[/]\n\n[dim]{report.resolve()}[/]");self.source_table(d.get("sources",[]));p=self.query_one("#findings",Log);p.clear()
  for x in d.get("sources",[]):
   if x.get("finding")=="finding" or x.get("error"):p.write_line(f"[bold #e6465c]{str(x.get('source','SOURCE')).upper()}[/] · {x.get('provider_status','—')}");[p.write_line(f"{k:<22} {v}") for k,v in self.readable(x.get("data"))];p.write_line("")
  self.query_one("#breaches",Log).clear()
 def render_username(self,raw,d,report):
  s=d.get("summary",{});f=d.get("findings",{});profiles=f.get("profiles",[]);breaches=f.get("breaches",[]);self.query_one("#overview",Static).update(f"[bold]USERNAME INVESTIGATION[/]\n\nTarget       [bold]@{d.get('username','—')}[/]\nSources      {s.get('completed',0)} / {s.get('requested',0)}\nProfiles     [bold #42d39c]{len(profiles)}[/]\nBreaches     [bold #e6465c]{s.get('breach_findings',len(breaches))}[/]\nHistorical   [bold #58aee0]{len(f.get('historical',[]))}[/]\n\n[dim]{report.resolve()}[/]");self.source_table(raw.get("sources",[]),True);p=self.query_one("#findings",Log);p.clear()
  if not profiles:p.write_line("No verified profiles / Doğrulanmış profil bulunamadı.")
  for i,x in enumerate(profiles[:100],1):p.write_line(f"[bold #42d39c]{i:02}. {x.get('name') or x.get('username') or 'Profile'}[/]");p.write_line(str(x.get("url") or x.get("web_url") or x.get("canonical_url") or "—"));p.write_line(f"{x.get('status','unverified')} · {round(float(x.get('confidence') or 0)*100)}%\n")
  self.render_breaches(breaches)
 def render_breaches(self,items):
  p=self.query_one("#breaches",Log);p.clear();shown=0
  for b in items[:100]:
   if not isinstance(b,dict):continue
   for r in (b.get("records") if isinstance(b.get("records"),list) else [b])[:100]:
    if not isinstance(r,dict):continue
    shown+=1;sources=r.get("sources") or b.get("breach_sources") or [];fields=r.get("exposed_fields") or b.get("exposed_fields") or [];hashes=r.get("hash_types_observed") or [];signal="YES / EVET" if r.get("password_exposed") is True else "NO / HAYIR" if r.get("password_exposed") is False else "UNKNOWN";p.write_line(f"[bold #e6465c]BREACH {shown:02}[/]  {', '.join(map(str,sources)) or b.get('source','record')}");p.write_line(f"Provider         {b.get('source') or r.get('provider') or '—'}\nRisk             {r.get('risk') or b.get('risk') or 'unknown'}\nExposed fields   {', '.join(map(str,fields)) or '—'}\nPassword signal  {signal}\nHash types       {', '.join(map(str,hashes)) or '—'}\n")
  if not shown:p.write_line("Selected sources returned no verified breach records.\nSeçilen kaynaklar doğrulanmış ihlâl kaydı döndürmedi.")
 @on(DataTable.RowSelected,"#source-table")
 def inspect(self,e):
  x=self.source_data.get(str(e.row_key.value));p=self.query_one("#findings",Log)
  if not x:return
  p.clear();p.write_line(f"[bold #e6465c]{str(x.get('source','SOURCE')).upper()}[/]");p.write_line(f"Status  {x.get('verification_status') or x.get('provider_status') or x.get('status') or '—'}\n");[p.write_line(f"{k:<22} {v}") for k,v in self.readable(x)];self.query_one("#results",TabbedContent).active="tab-findings"
 def readable(self,v,prefix="",depth=0):
  rows=[]
  if depth>3:return rows
  if isinstance(v,dict):
   for k,x in v.items():
    if k in {"source","number","status"}:continue
    label=f"{prefix}.{k}" if prefix else str(k)
    if isinstance(x,(dict,list,tuple)):rows.extend(self.readable(x,label,depth+1))
    elif x not in (None,"",False):rows.append((label.replace("_"," ")[:21],str(x)[:240]))
  elif isinstance(v,(list,tuple)):
   for i,x in enumerate(v[:25],1):
    label=f"{prefix} #{i}"
    if isinstance(x,(dict,list,tuple)):rows.extend(self.readable(x,label,depth+1))
    elif x not in (None,""):rows.append((label[:21],str(x)[:240]))
  return rows[:80]

def main():GokboruApp().run()
if __name__=="__main__":main()
