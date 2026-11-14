"""Standalone screenshot/RGB diagnostic. Does not import GUI, gates or transport.

No input, UDP, config writes or monitor. Rectangles use exclusive right/bottom.
Desktop MSS captures can be occluded: visibility/foreground checks reduce but do
not eliminate overlays. A color candidate is NOT automatically a WeakAura.
"""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
import sys
import numpy as np
from wow_window import WindowError, physical_pixels, find_wow_client, wow_client_to_screen

COLORS = {'blue': (0, 0, 255), 'green': (0, 255, 0)}


def scan_regions(rgb, target, tolerance=20):
    mask = np.all(np.abs(rgb.astype(np.int16) - np.array(target, dtype=np.int16)) <= tolerance, axis=2)
    height, width = mask.shape
    seen = np.zeros(mask.shape, dtype=bool)
    regions = []
    for sy, sx in zip(*np.nonzero(mask)):
        if seen[sy, sx]:
            continue
        queue = deque([(int(sx), int(sy))])
        seen[sy, sx] = True
        left = right = int(sx)
        top = bottom = int(sy)
        area = 0
        while queue:
            x, y = queue.popleft()
            area += 1
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            for nx, ny in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    queue.append((nx, ny))
        bw, bh = right-left+1, bottom-top+1
        fill = area/(bw*bh)
        if not (10 <= bw <= 65 and 10 <= bh <= 65 and min(bw,bh)/max(bw,bh) >= .75 and fill >= .90):
            continue
        cx, cy = (left+right)//2, (top+bottom)//2
        if not mask[cy,cx]:
            continue
        regions.append({'bbox_client': [left,top,right+1,bottom+1], 'width':bw,'height':bh,
                        'area':area,'fill_ratio':fill,'center_client':[cx,cy],
                        'geometric_center_client':[(left+right)/2,(top+bottom)/2],
                        'center_rgb':[int(v) for v in rgb[cy,cx]],
                        'score':round(fill*2 + min(bw,bh)/max(bw,bh) - abs((bw+bh)/2-28)/65, 6)})
    return sorted(regions,key=lambda r:r['score'],reverse=True)


def inspect_frame(client, rgb, points=()):
    candidates = {name:scan_regions(rgb,color) for name,color in COLORS.items()}
    for regions in candidates.values():
        for region in regions:
            region['center_screen'] = list(wow_client_to_screen(client,*region['center_client']))
            l,t,r,b = region['bbox_client']
            ox,oy = client.client_origin_screen_x,client.client_origin_screen_y
            region['bbox_screen'] = [l+ox,t+oy,r+ox,b+oy]
    pairs=[]
    for bi,blue in enumerate(candidates['blue']):
        for gi,green in enumerate(candidates['green']):
            dy=abs(blue['center_client'][1]-green['center_client'][1])
            if dy <= max(blue['height'],green['height'])/2:
                pairs.append({'blue_index':bi,'green_index':gi,'y_difference':dy,
                              'score':blue['score']+green['score']-dy/30})
    pairs.sort(key=lambda p:p['score'],reverse=True)
    old={}
    for name, point, color in [('Node_Target',(32,277),'blue'),('Node_Mark',(110,276),'green')]:
        x,y=point[0]-client.client_origin_screen_x,point[1]-client.client_origin_screen_y
        inside=0 <= x < client.client_width and 0 <= y < client.client_height
        old[name]={'screen':list(point),'client':[x,y],'inside_client':inside,
                   'rgb': [int(v) for v in rgb[y,x]] if inside else None,
                   'containing_candidate_indices':[i for i,r in enumerate(candidates[color])
                       if r['bbox_client'][0] <= x < r['bbox_client'][2] and r['bbox_client'][1] <= y < r['bbox_client'][3]]}
    sampled=[]
    for x,y in points:
        screen=wow_client_to_screen(client,x,y)
        sampled.append({'client':[x,y],'screen':list(screen),'rgb':[int(v) for v in rgb[y,x]]})
    return {'candidates':candidates,'aligned_pairs':pairs,'old_nodes':old,'specified_points':sampled}


def capture_diagnostic(expected_image=None, points=(), screenshot=None, allow_partial=False):
    # Separate process + thread-local PMv2: no DPI mutation of existing Tk GUI.
    import mss
    from wow_window import _libraries
    with physical_pixels():
        client=find_wow_client(expected_image)
        from wow_geometry_trace import snapshot,assert_unchanged
        before=snapshot(client,stage='diagnostic_before_mss')
        for x,y in points:
            wow_client_to_screen(client,x,y)  # Fail before capture on invalid input.
        u,_=_libraries()
        import ctypes as c
        from ctypes import wintypes as w
        u.GetForegroundWindow.argtypes,u.GetForegroundWindow.restype=[],w.HWND
        if u.GetForegroundWindow() != client.hwnd:
            raise WindowError('not_foreground','WoW must be foreground; tool will not activate it')
        with (getattr(mss,'MSS',None) or mss.mss)() as sct:
            desktop=sct.monitors[0]
            x,y=client.client_origin_screen_x,client.client_origin_screen_y
            left,top=max(x,desktop['left']),max(y,desktop['top'])
            right=min(x+client.client_width,desktop['left']+desktop['width'])
            bottom=min(y+client.client_height,desktop['top']+desktop['height'])
            partial=(left,top,right,bottom) != (x,y,x+client.client_width,y+client.client_height)
            if right <= left or bottom <= top:
                raise WindowError('client_off_desktop','No visible client intersection')
            if partial and not allow_partial:
                raise WindowError('client_off_desktop','Client is not entirely on virtual desktop')
            for px,py in points:
                sx,sy=wow_client_to_screen(client,px,py)
                if not (left <= sx < right and top <= sy < bottom):
                    raise WindowError('point_not_visible','Requested client point is outside desktop intersection')
            roi={'left':left,'top':top,'width':right-left,'height':bottom-top}
            before.update(mss_monitors=[dict(m) for m in sct.monitors],roi=roi)
            shot=sct.grab(roi)
            after_client=find_wow_client(expected_image)
            assert_unchanged(before,snapshot(after_client,[dict(m) for m in sct.monitors],roi,'diagnostic_after_grab'),
                             original_equal=after_client==client)
            # Uncaptured edges are excluded from point results. Black padding can
            # never create blue/green candidates; it is not reported as sampled RGB.
            rgb=np.zeros((client.client_height,client.client_width,3),dtype=np.uint8)
            rgb[top-y:bottom-y,left-x:right-x]=np.asarray(shot)[:,:,:3][:,:,::-1]
            result=inspect_frame(client,rgb,points)
            for node in result['old_nodes'].values():
                sx,sy=node['screen']
                node['inside_captured_area']=left <= sx < right and top <= sy < bottom
                if not node['inside_captured_area']:
                    node['rgb']=None
            # Same frozen frame vs independent ClientToScreen OS call. Both must agree.
            for regions in result['candidates'].values():
                for region in regions:
                    px,py=region['center_client']
                    pt=w.POINT(px,py)
                    if not u.ClientToScreen(client.hwnd,c.byref(pt)) or [pt.x,pt.y] != region['center_screen']:
                        raise WindowError('conversion_mismatch','ClientToScreen disagrees with pure conversion')
                    region['verification_rgb']=list(sct.grab({'left':pt.x,'top':pt.y,'width':1,'height':1}).pixel(0,0))
                    region['independent_screen_pixel_matches']=region['verification_rgb']==region['center_rgb']
            result.update(status='ok',timestamp_utc=datetime.now(timezone.utc).isoformat(),
                          client=client.to_dict(),tolerance=20,connectivity=4,
                          bbox_convention='right/bottom exclusive',
                          partial_client=partial,captured_bbox_client=[left-x,top-y,right-x,bottom-y],
                          screenshot_origin_client=[left-x,top-y],
                          capture='MSS physical desktop pixels; client area only; overlays possible',
                          identity='verified Wow.exe process image; color candidates not automatic WA identity')
            if screenshot:
                from mss.tools import to_png
                to_png(shot.rgb,shot.size,output=screenshot)
                result['screenshot']=screenshot
            return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-image')
    parser.add_argument('--point',nargs=2,type=int,action='append',default=[])
    parser.add_argument('--screenshot',help='Optional output PNG; never a WoW/config file')
    parser.add_argument('--allow-partial-client',action='store_true',help='Explicitly capture only client/desktop intersection; report missing edges')
    args=parser.parse_args()
    try:
        result=capture_diagnostic(args.expected_image,args.point,args.screenshot,args.allow_partial_client)
    except WindowError as exc:
        result={'status':'error','code':exc.code,'message':str(exc)}
    except Exception as exc:
        result={'status':'error','code':'capture_failed','message':f'{type(exc).__name__}: {exc}'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='ok' else 2


if __name__ == '__main__':
    sys.exit(main())
