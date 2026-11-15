"""Fixed-layout visible-digit reader prototype. No capture, input, network or transport."""
from pathlib import Path
import json

def glyphs(image):
    if image.size!=(1920,1080):raise ValueError('需要1920x1080')
    image=image.convert('RGB')
    def on(x,y):
        rgb=image.getpixel((x,y));return min(rgb)>180 and max(rgb)-min(rgb)<60
    runs=[]
    for x in range(625,701):
        if any(on(x,y) for y in range(782,794)):
            if not runs or x>runs[-1][-1]+1:runs.append([x])
            else:runs[-1].append(x)
    masks=[]
    for run in runs:
        ys=[y for y in range(782,794) if any(on(x,y) for x in run)]
        if not ys:raise ValueError('空白字元')
        masks.append([''.join('1' if on(x,y) else '0' for x in run) for y in range(min(ys),max(ys)+1)])
    return masks

def read(image,templates=None):
    templates=templates if templates is not None else json.loads(Path(__file__).with_name('templates.json').read_text(encoding='utf-8'))
    masks=glyphs(image);chars=[]
    # Exact known raster only; unfamiliar glyphs fail closed rather than guessing.
    for mask in masks:
        labels={t['label'] for t in templates if t['mask']==mask}
        if len(labels)!=1:return {'status':'unavailable','reason':'未知或模糊字形'}
        chars.append(next(iter(labels)))
    text=''.join(chars)
    if text.count('/')!=1:return {'status':'unavailable','reason':'缺少完整資源文字'}
    a,b=text.split('/')
    if not a.isdecimal() or b!='100' or not 0<=int(a)<=100:return {'status':'unavailable','reason':'資源文字格式不符'}
    return {'status':'ok','focus':int(a),'text':text}

def crosscheck(image,bar_value):
    result=read(image)
    if result['status']!='ok':return dict(result,advisory_allowed=False)
    delta=abs(result['focus']-bar_value)
    return dict(result,bar_focus=bar_value,delta=delta,synchronized=delta<=1,
                advisory_allowed=delta<=1,output_allowed=False)
