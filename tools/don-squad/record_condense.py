#!/usr/bin/env python3
import argparse,json,pathlib,hashlib,os,datetime

def canon(o):return json.dumps(o,sort_keys=True,separators=(',',':')).encode()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--state-root',default=str(pathlib.Path(os.environ.get('XDG_STATE_HOME',pathlib.Path.home()/'.local/state'))/'don-squad'));ns=ap.parse_args();root=pathlib.Path(ns.state_root);evp=root/'events/events.jsonl';out=root/'receipts';out.mkdir(parents=True,exist_ok=True)
 if not evp.exists():print(json.dumps({'status':'blocked','reason':'no event log'}));return 2
 sessions={}
 for line in evp.read_text(errors='replace').splitlines():
  try:e=json.loads(line)
  except:continue
  sid=e.get('session_id')
  if not sid:continue
  s=sessions.setdefault(sid,{'session_id':sid,'start':None,'return':None,'agent':None,'agent_sha256':None,'model':None,'logic_level':None,'authority':None,'known_actions':[],'proven_actions':[],'test_results':[],'failures':[]})
  if e.get('type')=='agent.start' and not s['start']:
   s['start']=e.get('ts');s['agent']=e.get('agent');s['agent_sha256']=e.get('agent_sha256');s['model']=e.get('model');s['logic_level']=(e.get('model') or {}).get('variant');s['authority']=e.get('authority')
  elif e.get('type')=='agent.return':s['return']=e.get('ts')
  elif e.get('type')=='action.request':s['known_actions'].append({'ts':e.get('ts'),'action':e.get('action'),'resources':e.get('resources'),'effect':e.get('effect')})
  elif e.get('type')=='tool.after':
   rec={'ts':e.get('ts'),'tool':e.get('tool'),'status':e.get('status')}
   if e.get('test_kind'): s['test_results'].append({'ts':e.get('ts'),'kind':e.get('test_kind'),'status':e.get('status'),'proven':bool(e.get('proven'))})
   (s['proven_actions'] if e.get('proven') else s['failures']).append(rec)
 for sid,s in sessions.items():
  if not s['start']:continue
  s['complete']=bool(s['return']);s['status']='completed' if s['return'] and not s['failures'] else ('failed' if s['failures'] else 'incomplete')
  if s['start'] and s['return']:
   try:s['duration_seconds']=(datetime.datetime.fromisoformat(s['return'].replace('Z','+00:00'))-datetime.datetime.fromisoformat(s['start'].replace('Z','+00:00'))).total_seconds()
   except:s['duration_seconds']=None
  else:s['duration_seconds']=None
  s['recorded_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();s['record_sha256']=hashlib.sha256(canon(s)).hexdigest();(out/(sid+'.json')).write_text(json.dumps(s,indent=2)+'\n')
 print(json.dumps({'status':'completed','sessions':len(sessions),'receipts':str(out)}))
 return 0
if __name__=='__main__':raise SystemExit(main())
