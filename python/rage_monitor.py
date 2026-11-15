"""Read-only fixed-layout rage estimate. No input or transport imports."""
import json
from statistics import median

def estimate(image):
    if image.size!=(1920,1080):raise ValueError('需要1920x1080遊戲視窗，請重新校準')
    counts=[]
    for y in (778,779,780):
        bits=[]
        for x in range(513,815):
            r,g,b=image.getpixel((x,y))[:3]
            bits.append(r>=160 and r-g>=90 and r-b>=90)
        count=0;miss=0
        if any(bits[:4]):
            for i,on in enumerate(bits):
                if on:count=i+1;miss=0
                else:miss+=1
                if miss>=3:break
        counts.append(count/len(bits))
    value=round(median(counts)*100)
    if max(counts)-min(counts)>.08:raise ValueError('取樣線不一致，可能被遮擋；請檢查怒氣條')
    return {'estimated_rage':value,'assumed_maximum':100,'approximate':True}

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
        result=estimate(im);result['status']='ok'
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
        snapshot={'timestamp':time.monotonic(),'source':'live_pixels_partial','identity':identity,'rage':result['estimated_rage'],
                  'target':match(nodes['Node_Target']),'combat':match(nodes['Node_Combat']),'enemy':None,
                  'skills':{n:{'visual_match':match(nodes[n]),'cooldown_ready':None,'in_range':None,'usable':None} for n in SKILL_PRIORITY}}
        if find_wow_client(foreground_only=True)!=c:raise ValueError('視窗位置已改變')
        result['integrated_snapshot']=snapshot
        return result
if __name__=='__main__':
    try:print(json.dumps(capture(),ensure_ascii=True))
    except Exception as e:print(json.dumps({'status':'unavailable','reason':str(e)},ensure_ascii=True))
