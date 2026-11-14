"""Read-only geometry evidence. Never normalizes, tolerates, or repairs a change."""
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime
import json, os, threading
from pathlib import Path
from wow_window import _libraries, WindowError

LOG = Path(__file__).with_name('diagnostics')/'geometry_changes.jsonl'
_lock = threading.Lock()

def snapshot(client, monitors=None, roi=None, stage=None):
    u,_ = _libraries()
    u.GetThreadDpiAwarenessContext.restype=c.c_void_p
    u.GetThreadDpiAwarenessContext.argtypes=[]
    u.GetAwarenessFromDpiAwarenessContext.argtypes=[c.c_void_p]
    u.GetAwarenessFromDpiAwarenessContext.restype=c.c_int
    u.AreDpiAwarenessContextsEqual.argtypes=[c.c_void_p,c.c_void_p]
    u.AreDpiAwarenessContextsEqual.restype=w.BOOL
    context=u.GetThreadDpiAwarenessContext()
    u.GetDpiForWindow.argtypes,u.GetDpiForWindow.restype=[w.HWND],w.UINT
    u.GetForegroundWindow.argtypes,u.GetForegroundWindow.restype=[],w.HWND
    rect=w.RECT();point=w.POINT(0,0)
    ok_rect=bool(u.GetClientRect(client.hwnd,c.byref(rect)))
    ok_origin=bool(u.ClientToScreen(client.hwnd,c.byref(point)))
    dwm=c.WinDLL('dwmapi');dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,c.c_void_p,w.DWORD]
    dwm.DwmGetWindowAttribute.restype=c.c_long
    bounds=w.RECT();hr=dwm.DwmGetWindowAttribute(client.hwnd,9,c.byref(bounds),c.sizeof(bounds))
    return dict(timestamp=datetime.now().astimezone().isoformat(timespec='microseconds'),
        process_pid=os.getpid(),thread_id=threading.get_ident(),stage=stage,
        client=client.to_dict(),client_type=type(client).__module__+'.'+type(client).__qualname__,
        dpi_context={'raw':context,'awareness':u.GetAwarenessFromDpiAwarenessContext(context),
            'pmv2':bool(u.AreDpiAwarenessContextsEqual(context,c.c_void_p(-4)))},
        window_dpi=u.GetDpiForWindow(client.hwnd),
        get_client_rect={'ok':ok_rect,'rect':[rect.left,rect.top,rect.right,rect.bottom]},
        client_to_screen={'ok':ok_origin,'point':[point.x,point.y]},
        dwm_extended_frame_bounds=[bounds.left,bounds.top,bounds.right,bounds.bottom] if hr==0 else {'hresult':hr},
        mss_monitors=monitors,foreground_hwnd=u.GetForegroundWindow(),roi=roi)

def differences(before,after):
    changes=[]
    def compare(category,path,a,b):
        if a!=b:
            item=dict(reason=category,field=path,before=a,after=b)
            if type(a) in (int,float) and type(b) in (int,float):item['delta']=b-a
            elif isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)) and len(a)==len(b) and all(type(v) in (int,float) for v in (*a,*b)):
                item['delta']=[y-x for x,y in zip(a,b)]
            changes.append(item)
    a,b=before['client'],after['client']
    for key in a:
        category=('window_identity_changed' if key in ('hwnd','pid','process_image') else
                  'client_size_changed' if key in ('client_width','client_height') else
                  'client_origin_changed' if key.startswith('client_origin') else
                  'window_title_changed' if key=='title' else 'window_rect_changed')
        compare(category,'client.'+key,a[key],b[key])
    for key,category in [('dpi_context','dpi_context_changed'),('window_dpi','window_dpi_changed'),
        ('foreground_hwnd','foreground_changed'),('mss_monitors','capture_bounds_changed'),
        ('get_client_rect','raw_client_rect_changed'),('client_to_screen','raw_client_origin_changed'),
        ('dwm_extended_frame_bounds','dwm_frame_changed'),('client_type','snapshot_type_changed')]:
        compare(category,key,before.get(key),after.get(key))
    return changes

def assert_unchanged(before,after,*,original_equal=True,stages=None):
    changes=differences(before,after)
    for stage in stages or []:
        for change in differences(before,stage):
            changes.append(dict(change,stage=stage.get('stage')))
    if not original_equal and not changes:
        changes=[dict(reason='snapshot_equality_changed',field='WowClient.__eq__',before=True,after=False)]
    if changes:
        record=dict(timestamp=after['timestamp'],event='GEOMETRY_CHANGE',
                    reasons=list(dict.fromkeys(d['reason'] for d in changes)),differences=changes,
                    before=before,after=after,stages=stages or [])
        with _lock:
            LOG.parent.mkdir(parents=True,exist_ok=True)
            with LOG.open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
        exc=WindowError(changes[0]['reason'],json.dumps(record,ensure_ascii=False))
        exc.geometry_evidence=record
        raise exc
