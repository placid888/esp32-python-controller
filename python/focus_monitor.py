"""Read-only fixed-layout focus estimate. No input or transport imports."""
import json
from statistics import median

def _estimate_bar(image):
    if image.size!=(1920,1080):raise ValueError('需要1920x1080遊戲視窗，請重新校準')
    counts=[]
    for y in (778,779,780):
        bits=[]
        for x in range(513,815):
            r,g,b=image.getpixel((x,y))[:3]
            bits.append(r>=120 and 35<=g<=190 and b<=110 and r-g>=35 and g-b>=20)
        count=0;miss=0
        if any(bits[:4]):
            for i,on in enumerate(bits):
                if on:count=i+1;miss=0
                else:miss+=1
                if miss>=3:break
        counts.append(count/len(bits))
    value=round(median(counts)*100)
    if max(counts)-min(counts)>.08:raise ValueError('取樣線不一致，可能被遮擋；請檢查集中值條')
    return {'estimated_focus':value,'assumed_maximum':100,'approximate':True,'calibration_status':'unverified'}

def estimate(image):
    """Only accept known visible digits consistent with the same-frame bar."""
    from focus_digits import crosscheck
    bar=_estimate_bar(image)
    checked=crosscheck(image,bar['estimated_focus'])
    if checked['status']!='ok':
        raise ValueError('集中值數字無法辨識：'+checked.get('reason','未知原因')+'；本次不產生提示')
    if not checked['synchronized']:
        raise ValueError('集中值讀值不同步（文字%s、條長%s）；等待更新，本次不產生提示'%(checked['focus'],bar['estimated_focus']))
    bar['bar_estimated_focus']=bar['estimated_focus']
    bar['estimated_focus']=checked['focus']
    bar['visible_text']=checked['text']
    bar['numeric_crosscheck']='consistent'
    return bar

def capture():
    import mss
    from PIL import Image
    from wow_window import physical_pixels,find_wow_client,wow_client_to_screen
    from wow_sampling import _check_visible_owner
    from wow_window import _libraries
    with physical_pixels():
        c=find_wow_client(foreground_only=True)
        if (c.client_width,c.client_height)!=(1920,1080):raise ValueError('需要1920x1080遊戲視窗')
        sx,sy=wow_client_to_screen(c,511,777)
        roi={'left':sx,'top':sy,'width':308,'height':22}
        u,_=_libraries();_check_visible_owner(u,c,roi)
        with (getattr(mss,'MSS',None) or mss.mss)() as sct:
            shot=sct.grab({'left':c.client_origin_screen_x,'top':c.client_origin_screen_y,'width':1920,'height':1080})
        if find_wow_client(foreground_only=True)!=c:raise ValueError('視窗位置已改變')
        _check_visible_owner(u,c,roi)
        im=Image.frombytes('RGB',shot.size,shot.rgb)
        result=estimate(im);result['status']='ok';result['calibration_status']='unverified';result['resource']='focus'
        import profile_store,time
        from decision import node_matches
        from skill_model import SKILL_PRIORITY
        data=profile_store.read(__import__('pathlib').Path(__file__).with_name('config.json'))
        profile=data['profiles'][data['last_used']]
        identity=[data['last_used'],profile['selected_class'],profile['selected_spec']]
        def match(node):
            if not node.get('enabled'):return None
            x,y=node['x'],node['y']
            if node.get('coordinate_mode','desktop_absolute')=='desktop_absolute':x-=c.client_origin_screen_x;y-=c.client_origin_screen_y
            size={'single_pixel':1,'3x3':3,'5x5':5}[node.get('sample_mode','single_pixel')];half=size//2
            wow_client_to_screen(c,x-half,y-half);wow_client_to_screen(c,x+half,y+half)
            rx,ry=wow_client_to_screen(c,x-half,y-half)
            _check_visible_owner(u,c,{'left':rx,'top':ry,'width':size,'height':size})
            hits=sum(node_matches(im.getpixel((xx,yy)),node) for yy in range(y-half,y+half+1) for xx in range(x-half,x+half+1))
            return hits/(size*size)>=node.get('match_ratio',.30)
        nodes=profile['nodes']
        snapshot={'timestamp':time.monotonic(),'source':'live_pixels_partial','calibration_status':'unverified','identity':identity,'focus':result['estimated_focus'],
                  'target':match(nodes['Node_Target']),'combat':match(nodes['Node_Combat']),'enemy':None,
                  'skills':{n:{'visual_match':match(nodes[n]),'cooldown_ready':None,'in_range':None,'usable':None} for n in SKILL_PRIORITY}}
        if find_wow_client(foreground_only=True)!=c:raise ValueError('視窗位置已改變')
        result['integrated_snapshot']=snapshot
        return result
if __name__=='__main__':
    try:print(json.dumps(capture(),ensure_ascii=True))
    except Exception as e:print(json.dumps({'status':'unavailable','reason':str(e)},ensure_ascii=True))
