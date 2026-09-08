from __future__ import annotations
import difflib,json,os,shlex,shutil,subprocess,sys,threading,time
from datetime import datetime
from pathlib import Path
from moriarty.services.username_audit import DEFAULT_USERNAME_SOURCES,compact_username_audit
from moriarty.report_viewer import render as render_report,gallery as open_gallery

ESC="\033[";RESET=ESC+"0m";BOLD=ESC+"1m";RED=ESC+"38;5;196m";BLUE=ESC+"38;5;39m";GREEN=ESC+"38;5;48m";YELLOW=ESC+"38;5;220m";GRAY=ESC+"38;5;244m";WHITE=ESC+"97m"
PHONE=("local","truecaller","syncme","telegram","facebook","whatsapp","cybernews","databreach","hudsonrock","github","reddit","brave","duckduckgo","web-mentions","pastebin","documents","reputation","business","disposable","opensanctions","ftc","btk")
USER=tuple(s.name for s in DEFAULT_USERNAME_SOURCES)
PRESETS={
 "phone":{"quick":("local","reputation","business","disposable"),"social":("local","truecaller","syncme","telegram","facebook","whatsapp"),"leaks":("local","cybernews","databreach","hudsonrock","pastebin"),"web":("local","github","brave","duckduckgo","web-mentions","documents")},
 "username":{"quick":("github","gitlab","whatsmyname","socialscan"),"social":tuple(s.name for s in DEFAULT_USERNAME_SOURCES if "social" in s.category or s.name in {"reddit","telegram","bluesky"}),"leaks":tuple(s.name for s in DEFAULT_USERNAME_SOURCES if s.category in {"breach_exposure","darkweb_index"}),"web":tuple(s.name for s in DEFAULT_USERNAME_SOURCES if s.category not in {"breach_exposure","darkweb_index","federated_profiles"})}}

def clear():print(ESC+"2J"+ESC+"H",end="")
def banner():
 print(f"""{RED}{BOLD}
     _______  Ö  K  B  Ö  R  Ü
    / _____/\\________________________________________
   / /  __  /  INTELLIGENCE OPERATIONS FRAMEWORK   /
  / /__/ / /_______________________________________/
 /______/       {BLUE}RECON  ·  CORRELATE  ·  ASSESS{RESET}

 {GRAY}+ -- --=[ Gökbörü Intelligence Console                         ]
 + -- --=[ Phone and username investigation modules                  ]
 + -- --=[ Local workspace · JSON evidence · structured reporting    ]{RESET}

 Type {WHITE}help{RESET} for commands or {WHITE}use username{RESET} to select a module.
 """)
def spin(process):
 frames="|/-\\";start=time.monotonic();i=0
 while process.poll() is None:
  elapsed=int(time.monotonic()-start);print(f"\r{BLUE}[*]{RESET} Investigation running {frames[i%4]}  {elapsed//60:02d}:{elapsed%60:02d}",end="",flush=True);i+=1;time.sleep(.12)
 print("\r"+" "*72+"\r",end="")
def table(headers,rows):
 widths=[len(str(x)) for x in headers]
 for row in rows:
  for i,value in enumerate(row):widths[i]=min(48,max(widths[i],len(str(value))))
 rule="+-"+"-+-".join("-"*w for w in widths)+"-+"
 print(GRAY+rule+RESET);print("| "+" | ".join(f"{WHITE}{str(v):<{widths[i]}}{RESET}" for i,v in enumerate(headers))+" |");print(GRAY+rule+RESET)
 for row in rows:print("| "+" | ".join(f"{str(v)[:widths[i]]:<{widths[i]}}" for i,v in enumerate(row))+" |")
 print(GRAY+rule+RESET)

class Console:
 def __init__(self):
  self.mode=None;self.target="";self.region="TR";self.timeout=60;self.authorized=False;self.sources=[];self.output="";self.raw=None;self.result=None
 def prompt(self):return f"{RED}gokboru{RESET}"+(f" {BLUE}{self.mode}{RESET}" if self.mode else "")+f" {WHITE}> {RESET}"
 def config(self):
  try:
   data=json.loads((Path.home()/".local/share/moriarty-v5/gokboru/configuration.json").read_text(encoding="utf-8"));return data if isinstance(data,dict) else {}
  except (OSError,json.JSONDecodeError):return {}
 def loop(self):
  clear();banner()
  while True:
   try:line=input(self.prompt()).strip()
   except (EOFError,KeyboardInterrupt):print();return 0
   if not line:continue
   try:parts=shlex.split(line)
   except ValueError as exc:print(f"{RED}[-]{RESET} {exc}");continue
   command=parts[0].lower();args=parts[1:]
   if command in {"exit","quit"}:return 0
   if command in {"phone","username"}:self.use([command]);continue
   if command in {"target","sources","authorized","region","timeout","output"}:self.set([command,*args]);continue
   if command=="help":self.help()
   elif command=="banner":banner()
   elif command=="clear":clear()
   elif command=="use":self.use(args)
   elif command=="set":self.set(args)
   elif command=="unset":self.unset(args)
   elif command=="show":self.show(args)
   elif command=="run":self.run()
   elif command=="open":self.open_view(args)
   elif command=="back":self.mode=None
   elif command=="web":subprocess.Popen([sys.executable,"-m","moriarty.web_workspace_entry"]);print(f"{GREEN}[+]{RESET} Web workspace started.")
   else:
    commands=["help","use","set","unset","show","run","web","back","banner","clear","exit","phone","username","target","sources","authorized","region","timeout","output"]
    guess=difflib.get_close_matches(command,commands,n=1,cutoff=.55)
    print(f"{RED}[-]{RESET} Unknown command: {command}."+(f" Did you mean {WHITE}{guess[0]}{RESET}?" if guess else f" Type {WHITE}help{RESET}."))
 def help(self):
  if not self.mode:
   print(f"\n{WHITE}{BOLD}GETTING STARTED{RESET}\n  First select what you want to investigate:\n")
   table(("COMMAND","WHAT IT DOES"),[("use phone","Investigate an authorized phone number"),("use username","Investigate a public username"),("phone / username","Short form of the commands above"),("web","Start the graphical Web workspace"),("exit","Close the console")])
   print(f"\n{GRAY}Example:{RESET}  use username\n")
   return
  common=[("target VALUE",f"Set the {'username' if self.mode=='username' else 'phone number'} to investigate"),("sources quick","Fast recommended source set"),("sources social","Social profile/presence sources"),("sources leaks","Breach and exposure sources"),("sources web","Open-web sources"),("sources all","Every available source (slow)"),("authorized yes","Required authorization confirmation"),("run","Start the configured investigation"),("show results","Complete case report"),("show outputs","List every output workspace and command"),("show social","Social-media output"),("show identity","Caller/profile identity output"),("show reputation","Comments and reputation output"),("show breaches","Breach output"),("show web","Open-web output"),("show documents","Document output"),("show business","Business output"),("show source NAME","Inspect one provider"),("show errors","Failed/blocked providers"),("show output","Display saved report path"),("open CATEGORY","Open output in a separate terminal"),("open gallery","Open profile images in local HTML")]
  if self.mode=="phone":common.extend([("region TR","Set the default phone region"),("show findings","Inspect positive findings")])
  else:common.extend([("show profiles","Display discovered profiles"),("show breaches","Display readable breach records")])
  common.extend([("back","Return to module selection"),("clear / banner / exit","Console controls")])
  ready=bool(self.target and self.sources and self.authorized)
  state=[("Selected module",self.mode.upper()),("Selected target",self.target or "NOT SET"),("Selected sources",f"{len(self.sources)} · {', '.join(self.sources)}" if self.sources else "NOT SET"),("Authorization","CONFIRMED" if self.authorized else "REQUIRED"),("Run state","READY" if ready else "INCOMPLETE"),("Last result","AVAILABLE · show results" if self.result else "NONE")]
  print(f"\n{WHITE}{BOLD}{self.mode.upper()} MODULE{RESET}\n")
  table(("SESSION STATE","CURRENT VALUE"),state)
  print(f"\n{WHITE}{BOLD}AVAILABLE COMMANDS{RESET}\n  Commands may be written with or without {WHITE}set{RESET}.\n")
  table(("COMMAND","DESCRIPTION"),common)
  next_commands=[]
  if not self.target:next_commands.append(f"target {'AzizKpln' if self.mode=='username' else '+905xxxxxxxxx'}")
  if not self.sources:next_commands.append("sources quick")
  if not self.authorized:next_commands.append("authorized yes")
  next_commands.extend(["show options","run"] if not ready else ["run"])
  print(f"\n{WHITE}{BOLD}{'READY TO RUN' if ready else 'NEXT COMMANDS'}{RESET}")
  for command in next_commands:print(f"  {command}")
  print()
 def use(self,args):
  if not args or args[0].lower() not in {"phone","username"}:print(f"{YELLOW}[!]{RESET} Usage: use phone | use username");return
  self.mode=args[0].lower();self.target="";self.authorized=False;self.sources=list(PRESETS[self.mode]["quick"]);self.result=None;print(f"{GREEN}[+]{RESET} Using {WHITE}{self.mode} intelligence{RESET} module. Type {WHITE}help{RESET} for module commands.\n{BLUE}[*]{RESET} Next: {WHITE}target {'USERNAME' if self.mode=='username' else 'PHONE_NUMBER'}{RESET}")
 def set(self,args):
  if len(args)==1 and args[0].lower() in {"phone","username"}:self.use([args[0]]);return
  if not self.mode:print(f"{YELLOW}[!]{RESET} Select a module first: use phone | use username");return
  if len(args)<2:print(f"{YELLOW}[!]{RESET} Usage: set OPTION VALUE");return
  key=args[0].lower();value=" ".join(args[1:])
  if key=="target":self.target=value
  elif key=="region":self.region=value.upper()
  elif key=="timeout":
   try:self.timeout=max(10,min(600,int(value)))
   except ValueError:print(f"{RED}[-]{RESET} Timeout must be a number.");return
  elif key=="authorized":self.authorized=value.lower() in {"yes","y","true","1","evet","e"}
  elif key=="output":self.output=value
  elif key=="sources":
   name=value.lower();available=set(USER if self.mode=="username" else PHONE)
   selected=list(available) if name=="all" else list(PRESETS[self.mode].get(name,tuple(x.strip() for x in name.split(",") if x.strip())))
   unknown=[x for x in selected if x not in available]
   if unknown:print(f"{RED}[-]{RESET} Unknown sources: {', '.join(unknown)}");return
   if self.mode=="username" and name=="leaks":
    selected=[x for x in selected if x!="localbreach"];c=self.config()
    if not(c.get("breachdirectory_api_key") or os.getenv("BREACHDIRECTORY_API_KEY") or os.getenv("RAPIDAPI_KEY")):selected=[x for x in selected if x!="breachdirectory"]
   self.sources=selected
  else:print(f"{RED}[-]{RESET} Unknown option: {key}");return
  print(f"{GREEN}{key.upper()} =>{RESET} {getattr(self,key) if hasattr(self,key) else value}")
  if key=="target" and not self.sources:print(f"{BLUE}[*]{RESET} Next: {WHITE}sources quick{RESET} (or: social, leaks, web, all)")
  elif key=="target" and not self.authorized:print(f"{BLUE}[*]{RESET} Sources already selected ({len(self.sources)}). Next: {WHITE}authorized yes{RESET}")
  elif key=="target":print(f"{GREEN}[+]{RESET} Session is ready. Type {WHITE}run{RESET}.")
  elif key=="sources" and not self.authorized:print(f"{BLUE}[*]{RESET} Next: {WHITE}authorized yes{RESET}")
  elif key=="authorized" and self.authorized:print(f"{GREEN}[+]{RESET} Required options are ready. Check with {WHITE}show options{RESET}, then type {WHITE}run{RESET}.")
 def unset(self,args):
  if not args:return
  key=args[0].lower()
  if key=="target":self.target=""
  elif key=="authorized":self.authorized=False
  elif key=="sources":self.sources=[]
  elif key=="output":self.output=""
 def show(self,args):
  what=args[0].lower() if args else "options"
  if what=="options":
   if not self.mode:print(f"{YELLOW}[!]{RESET} No module selected. Use phone or username.");return
   rows=[("MODE",self.mode,"READY"),("TARGET",self.target or "not set", "READY" if self.target else "REQUIRED"),("SOURCES",",".join(self.sources) or "not set","READY" if self.sources else "REQUIRED"),("AUTHORIZED","yes" if self.authorized else "no","READY" if self.authorized else "REQUIRED"),("REGION",self.region,"PHONE ONLY"),("TIMEOUT",str(self.timeout),"SECONDS"),("OUTPUT",self.output or "automatic","JSON")];table(("OPTION","CURRENT VALUE","STATE"),rows)
  elif what=="sources":
   available=USER if self.mode=="username" else PHONE if self.mode else ();table(("SOURCE","SELECTED"),[(x,"yes" if x in self.sources else "no") for x in available])
  elif what=="results":self.show_results()
  elif what=="profiles":self.show_profiles() if self.mode=="username" else (render_report(self.result,"profiles") if self.result else print(f"{YELLOW}[!]{RESET} No investigation results."))
  elif what=="breaches":self.show_breaches() if self.mode=="username" else (render_report(self.result,"breaches") if self.result else print(f"{YELLOW}[!]{RESET} No investigation results."))
  elif what=="findings":self.show_findings()
  elif what=="source":self.show_source(args[1] if len(args)>1 else "")
  elif what=="errors":self.show_errors()
  elif what in {"report","output"}:print(f"{BLUE}[*]{RESET} {Path(self.output).resolve() if self.output else 'No report has been created.'}")
  elif what in {"outputs","categories"}:self.show_output_index()
  elif what=="json":print(json.dumps(self.result,ensure_ascii=False,indent=2) if self.result else f"{YELLOW}[!]{RESET} No investigation results.")
  elif what in {"social","identity","reputation","web","documents","business","news","companies","all","history"}:
   render_report(self.result,what) if self.result else print(f"{YELLOW}[!]{RESET} No investigation results.")
  else:print(f"{RED}[-]{RESET} Unknown view: {what}")
 def open_view(self,args):
  if not self.result or not self.output:print(f"{YELLOW}[!]{RESET} Run an investigation first.");return
  category=args[0].lower() if args else "all"
  if category=="gallery":
   open_gallery(self.result,Path(self.output));return
  allowed={"all","social","profiles","identity","reputation","breaches","web","documents","business","news","companies","errors","history"}
  if category not in allowed:print(f"{RED}[-]{RESET} Unknown output category: {category}");return
  command=f"{shlex.quote(sys.executable)} -m moriarty.report_viewer {shlex.quote(str(Path(self.output).resolve()))} {shlex.quote(category)}; printf '\nPress Enter to close...'; read"
  terminal=shutil.which("gnome-terminal")
  if terminal:subprocess.Popen([terminal,"--","bash","-lc",command]);print(f"{GREEN}[+]{RESET} Opened {category} output in a new terminal.");return
  terminal=shutil.which("x-terminal-emulator")
  if terminal:subprocess.Popen([terminal,"-e","bash","-lc",command]);print(f"{GREEN}[+]{RESET} Opened {category} output in a new terminal.");return
  print(f"{YELLOW}[!]{RESET} No supported terminal launcher found; displaying here.");render_report(self.result,category)
 def show_output_index(self):
  if not self.result:print(f"{YELLOW}[!]{RESET} Run an investigation first.");return
  commands=[("social","Social accounts, caller-ID profiles and presence"),("profiles","Profile records and available image links"),("identity","Names, number metadata and identity signals"),("reputation","Phone comments, complaints and reputation"),("breaches","Breach and exposure records"),("web","Open-web mentions and discovered pages"),("documents","Documents and files"),("business","Business/registry records"),("errors","Failed or blocked providers"),("all","Every structured result")]
  print(f"\n{WHITE}{BOLD}AVAILABLE OUTPUT WORKSPACES{RESET}")
  table(("CATEGORY","SHOW HERE","OPEN SEPARATELY","CONTENTS"),[(x,f"show {x}",f"open {x}",d) for x,d in commands])
  print(f"\n{BLUE}Profile gallery:{RESET} open gallery\n{BLUE}Report path:{RESET} show output")
 def show_findings(self):
  if not self.result:print(f"{YELLOW}[!]{RESET} No investigation results.");return
  if self.mode=="username":self.show_profiles();return
  findings=[x for x in self.result.get("sources",[]) if x.get("finding")=="finding"]
  if not findings:print(f"{YELLOW}[!]{RESET} No positive findings.");return
  print(f"\n{WHITE}{BOLD}POSITIVE FINDINGS · {len(findings)}{RESET}")
  for index,item in enumerate(findings,1):
   name=str(item.get("source","source"));print(f"\n{RED}[{index:02}] {name.upper()}{RESET}  {item.get('provider_status') or item.get('state') or '—'}")
   rows=self.flatten(item.get("data"))
   for key,value in rows[:35]:print(f"     {GRAY}{key:<22}{RESET} {value}")
   if len(rows)>35:print(f"     {GRAY}... {len(rows)-35} additional fields; use: show source {name}{RESET}")
  print(f"\n{GRAY}Inspect one provider:{RESET} show source SOURCE_NAME")
 def show_source(self,name):
  if not self.result:print(f"{YELLOW}[!]{RESET} No investigation results.");return
  if not name:print(f"{YELLOW}[!]{RESET} Usage: show source SOURCE_NAME\n  Run show sources to see names.");return
  sources=(self.raw or {}).get("sources",[]) if self.mode=="username" else self.result.get("sources",[])
  item=next((x for x in sources if str(x.get("source","")).lower()==name.lower()),None)
  if not item:print(f"{RED}[-]{RESET} Source not present in this result: {name}");return
  print(f"\n{WHITE}{BOLD}SOURCE RECORD · {str(item.get('source')).upper()}{RESET}")
  table(("PROPERTY","VALUE"),self.flatten(item)[:120])
 def show_errors(self):
  if not self.result:print(f"{YELLOW}[!]{RESET} No investigation results.");return
  sources=(self.raw or {}).get("sources",[]) if self.mode=="username" else self.result.get("sources",[])
  failed=[x for x in sources if (x.get("verification_status") or x.get("state") or x.get("status")) not in {"found","not_found","completed","success"} or x.get("error")]
  rows=[(x.get("source","—"),x.get("verification_status") or x.get("provider_status") or x.get("state") or x.get("status") or "—",x.get("error") or x.get("note") or "—") for x in failed]
  table(("SOURCE","STATUS","DETAIL"),rows) if rows else print(f"{GREEN}[+]{RESET} No provider errors.")
 def flatten(self,value,prefix="",depth=0):
  rows=[]
  if depth>4:return rows
  if isinstance(value,dict):
   for key,item in value.items():
    label=f"{prefix}.{key}" if prefix else str(key)
    if isinstance(item,(dict,list,tuple)):rows.extend(self.flatten(item,label,depth+1))
    elif item not in (None,""):rows.append((label.replace("_"," ")[:36],str(item)[:500]))
  elif isinstance(value,(list,tuple)):
   for index,item in enumerate(value[:100],1):
    label=f"{prefix} #{index}"
    if isinstance(item,(dict,list,tuple)):rows.extend(self.flatten(item,label,depth+1))
    elif item not in (None,""):rows.append((label[:36],str(item)[:500]))
  return rows
 def run(self):
  if not self.mode:print(f"{YELLOW}[!]{RESET} Select a module first.");return
  missing=[]
  if not self.target:missing.append("TARGET")
  if not self.sources:missing.append("SOURCES")
  if not self.authorized:missing.append("AUTHORIZED")
  if missing:
   print(f"{RED}[-]{RESET} Missing required options: {', '.join(missing)}")
   if "TARGET" in missing:print(f"  {BLUE}→{RESET} target {'USERNAME' if self.mode=='username' else '+90xxxxxxxxxx'}")
   if "SOURCES" in missing:print(f"  {BLUE}→{RESET} sources quick")
   if "AUTHORIZED" in missing:print(f"  {BLUE}→{RESET} authorized yes")
   return
  if self.mode=="username":cmd=[sys.executable,"-m","moriarty","username-audit",self.target,"--sources",",".join(self.sources),"--timeout",str(self.timeout),"--wmn-limit","180","--exposure-limit","20","--full-json"]
  else:
   cmd=[sys.executable,"-m","moriarty.web_phone_audit_entry",self.target,"--sources",",".join(self.sources),"--timeout",str(self.timeout),"--i-own-this-number","--region",self.region]
   if "telegram" in self.sources:cmd += ["--telegram-account",self.target]
   if os.name!="nt" and shutil.which("xvfb-run"):cmd=[shutil.which("xvfb-run"),"-a"]+cmd
  env=os.environ.copy();c=self.config()
  if c.get("breachdirectory_api_key"):env.setdefault("BREACHDIRECTORY_API_KEY",str(c["breachdirectory_api_key"]))
  if c.get("github_token"):env.setdefault("GITHUB_TOKEN",str(c["github_token"]))
  print(f"{BLUE}[*]{RESET} Target: {WHITE}{self.target}{RESET}\n{BLUE}[*]{RESET} Sources: {len(self.sources)}")
  process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env);worker=threading.Thread(target=spin,args=(process,),daemon=True);worker.start();stdout,stderr=process.communicate();worker.join(1)
  if process.returncode:print(f"{RED}[-]{RESET} Investigation failed.\n{stderr or stdout}");return
  try:self.raw=json.loads(stdout);self.result=compact_username_audit(self.raw) if self.mode=="username" else self.raw
  except json.JSONDecodeError:print(f"{RED}[-]{RESET} Invalid response.\n{stdout[-1500:]}");return
  path=Path(self.output or f"reports/gokboru-{self.mode}-{datetime.now():%Y%m%d-%H%M%S}.json").expanduser();path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(self.result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");self.output=str(path)
  print(f"{GREEN}[+]{RESET} Investigation complete. Report: {WHITE}{path.resolve()}{RESET}");self.show_results()
 def show_results(self):
  if not self.result:print(f"{YELLOW}[!]{RESET} No investigation results.");return
  s=self.result.get("summary",{})
  print(f"\n{RED}{BOLD}╔═ GÖKBÖRÜ CASE REPORT ═══════════════════════════════════════╗{RESET}")
  print(f"{RED}║{RESET} Target  {WHITE}{self.target:<25}{RESET} Module  {BLUE}{self.mode.upper():<12}{RESET} {RED}║{RESET}")
  print(f"{RED}╚══════════════════════════════════════════════════════════════╝{RESET}\n")
  if self.mode=="username":
   f=self.result.get("findings",{});profiles=f.get("profiles",[]);breaches=f.get("breaches",[]);historical=f.get("historical",[])
   confirmed=sum(x.get("status")=="confirmed" for x in profiles);probable=sum(x.get("status")=="probable" for x in profiles);unverified=len(profiles)-confirmed-probable
   table(("INTELLIGENCE SUMMARY","COUNT"),[("Profiles",len(profiles)),("Confirmed",confirmed),("Probable",probable),("Unverified",unverified),("Breach findings",s.get("breach_findings",len(breaches))),("Historical records",len(historical)),("Sources completed",f"{s.get('completed',0)}/{s.get('requested',0)}")])
   if self.raw:
    statuses={}
    for item in self.raw.get("sources",[]):
     status=str(item.get("verification_status") or item.get("status") or "unknown");statuses[status]=statuses.get(status,0)+1
    print(f"\n{WHITE}{BOLD}SOURCE HEALTH{RESET}")
    table(("STATUS","COUNT"),sorted(statuses.items(),key=lambda x:(x[0] not in {"found","not_found"},x[0])))
   print(f"\n{WHITE}{BOLD}HIGH-VALUE PROFILE FINDINGS{RESET}")
   if profiles:
    for index,x in enumerate(profiles[:10],1):
     name=x.get("name") or x.get("username") or "Profile";url=x.get("url") or x.get("web_url") or x.get("canonical_url") or "—";evidence=", ".join(map(str,x.get("evidence_sources",[]))) or "—"
     color=GREEN if x.get("status")=="confirmed" else YELLOW if x.get("status")=="probable" else GRAY
     print(f" {color}[{index:02}] {name}{RESET}  {x.get('status','unverified')} · {round(float(x.get('confidence') or 0)*100)}%")
     print(f"      {BLUE}{url}{RESET}\n      {GRAY}evidence: {evidence}{RESET}")
   else:print(f" {YELLOW}[!]{RESET} No verified profiles.")
   if breaches:
    print(f"\n{WHITE}{BOLD}BREACH INTELLIGENCE{RESET}");self.show_breaches(limit=5)
   if historical:
    print(f"\n{WHITE}{BOLD}HISTORICAL SIGNALS{RESET}")
    for index,x in enumerate(historical[:5],1):print(f" {BLUE}[{index:02}]{RESET} {x.get('archive') or x.get('source') or 'archive'} · {x.get('captured_at') or 'unknown date'}\n      {x.get('original_url') or x.get('url') or '—'}")
   print(f"\n{GRAY}More data:{RESET}  show profiles  |  show breaches  |  show sources\n{GRAY}JSON report:{RESET} {Path(self.output).resolve() if self.output else 'automatic'}\n")
  else:
   table(("INTELLIGENCE SUMMARY","COUNT"),[("Findings",s.get("findings",0)),("Clear",s.get("clear",0)),("Uncertain",s.get("indeterminate",0)),("Blocked",s.get("blocked",0)),("Failed",s.get("failed",0)),("Completed",f"{s.get('completed',0)}/{s.get('requested',0)}")])
   positives=[x for x in self.result.get("sources",[]) if x.get("finding")=="finding"]
   if positives:
    print(f"\n{WHITE}{BOLD}POSITIVE FINDINGS{RESET}")
    table(("SOURCE","STATUS","DURATION"),[(x.get("source","—"),x.get("provider_status","—"),f"{int(x.get('duration_ms',0) or 0)/1000:.1f}s") for x in positives[:20]])
    self.show_findings()
   print(f"\n{GRAY}Output workspaces:{RESET} show outputs  |  open social  |  open reputation  |  open gallery")
   print(f"{GRAY}JSON report:{RESET} {Path(self.output).resolve() if self.output else 'automatic'}\n")
 def show_profiles(self):
  if self.mode!="username" or not self.result:print(f"{YELLOW}[!]{RESET} No username profile results.");return
  rows=[]
  for x in self.result.get("findings",{}).get("profiles",[])[:100]:rows.append((x.get("name") or x.get("username") or "Profile",x.get("status","unverified"),f"{round(float(x.get('confidence') or 0)*100)}%",x.get("url") or x.get("web_url") or x.get("canonical_url") or "—"))
  table(("PROFILE","STATUS","CONF","URL"),rows) if rows else print(f"{YELLOW}[!]{RESET} No verified profiles.")
 def show_breaches(self,limit=100):
  if self.mode!="username" or not self.result:print(f"{YELLOW}[!]{RESET} No username breach results.");return
  rows=[]
  for b in self.result.get("findings",{}).get("breaches",[])[:limit]:
   for r in (b.get("records") if isinstance(b.get("records"),list) else [b])[:limit]:
    if len(rows)>=limit:break
    rows.append((",".join(map(str,r.get("sources") or b.get("breach_sources") or [])) or b.get("source","record"),r.get("risk") or b.get("risk") or "unknown",",".join(map(str,r.get("exposed_fields") or b.get("exposed_fields") or [])) or "—","yes" if r.get("password_exposed") else "no"))
  table(("BREACH SOURCE","RISK","EXPOSED FIELDS","PASSWORD"),rows) if rows else print(f"{YELLOW}[!]{RESET} No verified breach records.")

def main():return Console().loop()
if __name__=="__main__":raise SystemExit(main())
