"""Read-only geometry/DPI audit, no window changes and no input."""
import ctypes as c
from ctypes import wintypes as w
import json
import mss
from wow_window import physical_pixels,find_wow_client,_libraries


def candidate_inventory():
    """Inventory only: never picks or activates one of multiple clients."""
    import os
    from wow_window import _image,_geometry
    from wow_geometry_trace import snapshot
    u,k=_libraries();found=[]
    callback_type=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    @callback_type
    def visit(hwnd,unused):
        if not u.IsWindowVisible(hwnd):return True
        pid=w.DWORD();u.GetWindowThreadProcessId(hwnd,c.byref(pid));image=_image(k,pid.value)
        if not image or os.path.basename(image).lower()!='wow.exe':return True
        length=u.GetWindowTextLengthW(hwnd);title=c.create_unicode_buffer(length+1)
        u.GetWindowTextW(hwnd,title,len(title))
        record={'hwnd':int(hwnd),'pid':pid.value,'title':title.value,'image':image}
        try:record['snapshot']=snapshot(_geometry(u,hwnd,pid.value,title.value,image),stage='candidate_inventory_only')
        except Exception as exc:record.update(error_code=getattr(exc,'code',type(exc).__name__),error=str(exc))
        found.append(record);return True
    u.EnumWindows.argtypes,u.EnumWindows.restype=[callback_type,w.LPARAM],w.BOOL
    if not u.EnumWindows(visit,0):raise RuntimeError('EnumWindows failed')
    return found


def observe(seconds=5):
    """One attempt only; any geometry/identity change propagates immediately."""
    import time
    from wow_geometry_trace import snapshot,assert_unchanged
    records=[]
    with physical_pixels():
        client=find_wow_client()
        with (getattr(mss,'MSS',None) or mss.mss)() as sct:
            first=snapshot(client,[dict(m) for m in sct.monitors],stage='observation_start')
            records.append(first);start=time.monotonic()
            while time.monotonic()-start<seconds:
                current=find_wow_client()
                now=snapshot(current,[dict(m) for m in sct.monitors],stage='observation')
                assert_unchanged(first,now,original_equal=current==client)
                records.append(now);time.sleep(.1)
    return records


def main():
    u,_=_libraries()
    with physical_pixels():
        client=find_wow_client();hwnd=client.hwnd
        u.GetDpiForWindow.argtypes,u.GetDpiForWindow.restype=[w.HWND],w.UINT
        u.GetWindowLongPtrW.argtypes,u.GetWindowLongPtrW.restype=[w.HWND,c.c_int],c.c_ssize_t
        style=u.GetWindowLongPtrW(hwnd,-16)&0xffffffff
        exstyle=u.GetWindowLongPtrW(hwnd,-20)&0xffffffff
        result={'physical_client':client.to_dict(),'window_dpi':u.GetDpiForWindow(hwnd),
                'style_hex':hex(style),'exstyle_hex':hex(exstyle),
                'style_flags':{'WS_POPUP':bool(style&0x80000000),'WS_CAPTION':(style&0xc00000)==0xc00000,
                               'WS_THICKFRAME':bool(style&0x40000),'WS_MAXIMIZE':bool(style&0x1000000)}}
        dwm=c.WinDLL('dwmapi');dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,c.c_void_p,w.DWORD]
        dwm.DwmGetWindowAttribute.restype=c.c_long
        bounds=w.RECT();hr=dwm.DwmGetWindowAttribute(hwnd,9,c.byref(bounds),c.sizeof(bounds))
        result['dwm_extended_frame_bounds']=[bounds.left,bounds.top,bounds.right,bounds.bottom] if hr==0 else {'hresult':hr}
        with (getattr(mss,'MSS',None) or mss.mss)() as sct:result['mss_monitors']=sct.monitors
        contexts={}
        for label,value in [('unaware',-1),('system_aware',-2),('per_monitor_v2',-4)]:
            old=u.SetThreadDpiAwarenessContext(c.c_void_p(value))
            if not old:
                contexts[label]={'error':c.get_last_error()};continue
            try:
                rect=w.RECT();point=w.POINT(0,0)
                ok=bool(u.GetClientRect(hwnd,c.byref(rect)) and u.ClientToScreen(hwnd,c.byref(point)))
                contexts[label]={'ok':ok,'client_rect':[rect.left,rect.top,rect.right,rect.bottom],
                                 'origin_screen':[point.x,point.y]}
            finally:u.SetThreadDpiAwarenessContext(old)
        result['thread_context_comparison']=contexts
        result['root_cause']='unresolved: geometry observations do not establish why WoW chose this client size'
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
