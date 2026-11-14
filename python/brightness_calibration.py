"""Read-only calibration, independent of detector and transport."""
import copy, math, queue, statistics, threading, time
from skill_model import SKILL_PRIORITY

def region_brightness(pixels,ratio=.30):
    # Exactly the detector's per-pixel formula; no area-average substitution.
    values=sorted(((int(r)+int(g)+int(b))/3 for r,g,b in pixels),reverse=True)
    if not values or not 0<ratio<=1:raise ValueError('Invalid region / match ratio')
    # Detector matches iff count(pixel_brightness > threshold)/N >= ratio.
    # Therefore its equivalent brightness is the kth largest pixel, not mean(ROI).
    k=next(k for k in range(1,len(values)+1) if k/len(values)>=ratio)
    return values[k-1]

def summarize(values):
    if not values:raise ValueError('No valid calibration samples')
    return dict(samples=len(values),min=min(values),max=max(values),mean=statistics.mean(values),median=statistics.median(values))

def analyze(dark,bright):
    d=summarize(dark);b=summarize(bright);separation=b['median']-d['median']
    valid=separation>0;overlap=d['max']>=b['min']
    return dict(dark=d,bright=b,dark_median=d['median'],bright_median=b['median'],
        separation=separation,suggested_threshold=math.floor((d['median']+b['median'])/2) if valid else None,
        valid=valid,overlap=overlap,quality='良好' if separation>=40 else '可用，但建議實測' if separation>=20 else '警告：Brightness 可能不穩',
        warning='' if valid else '亮狀態沒有比暗狀態更亮，無法安全建立 Brightness Threshold。')

def apply_threshold(nodes,skill,result):
    if skill not in SKILL_PRIORITY:raise ValueError('Calibration is for Skills only')
    if nodes[skill]['mode']!='brightness':raise ValueError('Please select brightness mode yourself')
    if not result['valid']:raise ValueError(result['warning'])
    updated=copy.deepcopy(nodes);updated[skill]['threshold']=result['suggested_threshold'];return updated

class CalibrationJob:
    def __init__(self,node,vision_factory,count=15,period=.025):
        self.node=copy.deepcopy(node);self.vision_factory=vision_factory;self.count=count;self.period=period
        self.cancel_event=threading.Event();self.result=queue.Queue(maxsize=1);self.thread=None
    @property
    def alive(self):return bool(self.thread and self.thread.is_alive())
    def start(self):
        self.thread=threading.Thread(target=self.run,name='brightness-calibration',daemon=False);self.thread.start()
    def cancel(self):self.cancel_event.set()
    def run(self):
        vision=None;start=time.monotonic();values=[]
        try:
            vision=self.vision_factory()  # MSS created/used/closed on its owner thread.
            size={'single_pixel':1,'3x3':3,'5x5':5}[self.node.get('sample_mode','single_pixel')]
            for i in range(self.count):
                if self.cancel_event.is_set():return
                pixels=vision.get_region_rgb(self.node['x'],self.node['y'],size)
                if len(pixels)!=size*size:raise ValueError('Incomplete screenshot sample')
                values.append(region_brightness(pixels,self.node.get('match_ratio',.30)))
                if i+1<self.count and self.cancel_event.wait(max(0,start+(i+1)*self.period-time.monotonic())):return
            self.result.put_nowait(dict(values=values,summary=summarize(values),duration_ms=(time.monotonic()-start)*1000))
        except Exception as exc:self.result.put_nowait({'error':str(exc)})
        finally:
            if vision and hasattr(vision,'close'):vision.close()
