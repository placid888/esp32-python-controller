"""Bounded 1/2/3 hunter icon-only experiment. Default dry run; never changes original app gates."""
from pathlib import Path
import time,sys,json,hashlib,datetime,ctypes,argparse
ROOT=Path(__file__).parent;BASE=Path(__file__).resolve().parent;IDENTITY=('獵人','hunter','beast_mastery')
class Rotation:
 def __init__(self):self.busy_until=0.;self.entry_used=False
 def choose(self,focus,ready,target,combat,now,entry=False):
  # Focus deliberately ignored: only icon readiness and 1/2/3 priority govern choice.
  if target is not True:return None,'no_target'
  if now<self.busy_until:return None,'cast_or_global_interval'
  if combat is not True:return None,'waiting_for_manual_combat'
  for key in '123':
   if ready.get(key) is True:return key,'icon_priority_'+key
  return None,'icons_not_ready'
 def attempted(self,key,now):
  self.busy_until=now+(2.0 if key=='3' else 1.7)

def wait_for_game(probe,stopped,emit,clock=time.monotonic,sleep=time.sleep,timeout=60):
 deadline=clock()+timeout
 while clock()<deadline:
  if stopped():emit('stop_F12');return False
  try:probe();emit('game_foreground_ready');return True
  except Exception as error:
   # Wait only for a known foreground condition. Other errors must stay visible.
   if getattr(error,'code',None) not in ('wow_not_foreground','not_foreground'):raise
   emit('waiting_for_game',reason=str(error))
  sleep(.5)
 emit('startup_timeout',reason='60秒內未切回魔獸，沒有送技能鍵')
 return False

def compare(image,reference):
 ratios={}
 for key,left in [('1',566),('2',632),('3',698)]:
  hits=total=0
  for y in range(863,905,4):
   for x in range(left+7,left+48,4):
    a=image.getpixel((x,y));b=reference.getpixel((x-560,y-850))
    if max(b)<75:continue
    total+=1;hits+=all(abs(int(v)-int(w))<=25 for v,w in zip(a,b))
  ratios[key]=hits/max(total,1)
 return {k:v>=.85 for k,v in ratios.items()},ratios

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--start-on-target',action='store_true');args=parser.parse_args()
 sys.path.insert(0,str(BASE));import focus_monitor as monitor,profile_store
 from PIL import Image
 from wow_window import physical_pixels,find_wow_client,wow_client_to_screen,_libraries,WindowError
 from wow_sampling import _check_visible_owner
 cfg=BASE/'config.json';config_hash=hashlib.sha256(cfg.read_bytes()).hexdigest();data=profile_store.read(cfg);p=data['profiles'][data['last_used']]
 if (data['last_used'],p['selected_class'],p['selected_spec'])!=IDENTITY:raise RuntimeError('Wrong profile')
 reference=Image.open(ROOT/'hunter_123_reference.png').convert('RGB')
 out=ROOT/datetime.datetime.now().strftime('trial-%H%M%S');out.mkdir();counter=0;paired={};controller=None;rotation=Rotation();count=0;seen_combat=False
 (out/'hashes.json').write_text(json.dumps({n:hashlib.sha256((BASE/n).read_bytes()).hexdigest() for n in ['config.json','focus_monitor.py','focus_digits.py','templates.json','wow_window.py']},indent=2))
 def log(event,**fields):
  row=dict(event=event,time=datetime.datetime.now().astimezone().isoformat(),**fields)
  with (out/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
  print(json.dumps(row,ensure_ascii=False),flush=True)
 original=monitor.estimate
 def estimate(im):
  nonlocal paired
  with physical_pixels():
   c=find_wow_client(foreground_only=True);x,y=wow_client_to_screen(c,566,852);u,_=_libraries();_check_visible_owner(u,c,dict(left=x,top=y,width=190,height=60))
   ready,ratios=compare(im,reference);paired={'ready':ready,'ratios':ratios}
   im.crop((505,720,890,915)).save(out/('frame-%03d.png'%counter))
   im.crop((500,100,1400,330)).save(out/('errors-%03d.png'%counter))
  try:return original(im)
  except ValueError as error:
   paired['focus_note']=str(error)
   return {'estimated_focus':None,'bar_estimated_focus':None,'approximate':True,'calibration_status':'unverified'}
 monitor.estimate=estimate
 user=ctypes.WinDLL('user32',use_last_error=True);user.GetAsyncKeyState.argtypes=[ctypes.c_int];user.GetAsyncKeyState.restype=ctypes.c_short
 try:
  print('請切回魔獸；等待最多60秒，現在不送技能鍵。F12可結束。',flush=True)
  def probe_foreground():
   with physical_pixels():return find_wow_client(foreground_only=True)
  if not wait_for_game(probe_foreground,lambda:bool(user.GetAsyncKeyState(0x7b)&0x8000),log):return
  if args.live:
   from transport import ESP32Controller
   endpoint=p.get('udp_endpoint',{});controller=ESP32Controller(endpoint.get('host',''),endpoint.get('port',8888))
   if not controller.connect():raise RuntimeError(controller.last_error)
  end=time.monotonic()+30;log('start',live=args.live,seconds=30,max_attempts=10,start_on_target=args.start_on_target)
  while time.monotonic()<end:
   if user.GetAsyncKeyState(0x7b)&0x8000:log('stop_F12');break
   if hashlib.sha256(cfg.read_bytes()).hexdigest()!=config_hash:raise RuntimeError('Config changed')
   counter+=1;paired={}
   try:
    result=monitor.capture();snap=result['integrated_snapshot'];now=time.monotonic()
    if tuple(snap['identity'])!=IDENTITY:raise RuntimeError('Profile changed')
    seen_combat=seen_combat or snap['combat'] is True
    key,why=rotation.choose(result['estimated_focus'],paired['ready'],snap['target'],snap['combat'],now,args.start_on_target)
    log('sample',sequence=counter,focus=result['estimated_focus'],bar=result.get('bar_estimated_focus'),target=snap['target'],combat=snap['combat'],**paired,choice=key,reason=why)
    if seen_combat and snap['target'] is not True:log('stop_target_lost');break
    if key and count<10 and end-now>.5:
     with physical_pixels():find_wow_client(foreground_only=True)
     if user.GetAsyncKeyState(0x7b)&0x8000:break
     if time.monotonic()-snap['timestamp']>.5:continue
     queued=bool(controller.send_command({'action':'tap','key':key},source_node='Hunter_123_Icon_'+key)) if controller else False
     count+=1;rotation.attempted(key,time.monotonic());log('attempt',sequence=counter,key=key,queued=queued,live=args.live)
     if controller and not queued:raise RuntimeError(controller.last_error)
   except WindowError as exc:
    log('window_error',sequence=counter,code=exc.code,reason=str(exc))
    break
   except ValueError as exc:
    log('unavailable',sequence=counter,reason=str(exc))
    if 'foreground' in str(exc) or '點一下' in str(exc):break
   if controller:
    for ev in controller.poll_events():log('transport',detail=ev)
   time.sleep(.1)
 except Exception as error:
  import traceback
  log('fatal_error',error_type=type(error).__name__,reason=str(error),traceback=traceback.format_exc())
  raise
 finally:
  monitor.estimate=original
  if controller:
   controller.disconnect()
   if controller._thread:controller._thread.join(timeout=2)
   for ev in controller.poll_events():log('transport_final',detail=ev)
  log('stopped',attempts=count);print('RESULT',out,flush=True)
if __name__=='__main__':main()
