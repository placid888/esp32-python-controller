"""Fail-closed node sampling only; no GUI, gate, dispatch or transport imports."""
import ctypes as c
from ctypes import wintypes as w
import mss
from wow_window import physical_pixels, find_wow_client, wow_client_to_screen, WindowError, _libraries


def resolve_roi(client, node, size, monitors):
    if size not in (1,3,5):raise WindowError('invalid_roi','Unsupported ROI size')
    x,y=node['x'],node['y']
    sx,sy=wow_client_to_screen(client,x,y)
    half=size//2
    # Entire ROI must be in client, with no clamping or desktop fallback.
    wow_client_to_screen(client,x-half,y-half)
    wow_client_to_screen(client,x+half,y+half)
    left,top=sx-half,sy-half
    # Check real monitor union, not just bounding rectangle (which may have gaps).
    physical=monitors[1:] if len(monitors)>1 else monitors
    for px in range(left,left+size):
        for py in range(top,top+size):
            if not any(m['left']<=px<m['left']+m['width'] and m['top']<=py<m['top']+m['height'] for m in physical):
                raise WindowError('roi_not_capturable','ROI outside physical monitor coverage')
    return {'left':left,'top':top,'width':size,'height':size}


def _check_visible_owner(u,client,roi):
    u.GetForegroundWindow.argtypes,u.GetForegroundWindow.restype=[],w.HWND
    if u.GetForegroundWindow()!=client.hwnd:
        raise WindowError('not_foreground','WoW is not foreground; refusing desktop content')
    u.WindowFromPoint.argtypes,u.WindowFromPoint.restype=[w.POINT],w.HWND
    u.GetAncestor.argtypes,u.GetAncestor.restype=[w.HWND,w.UINT],w.HWND
    for x in range(roi['left'],roi['left']+roi['width']):
        for y in range(roi['top'],roi['top']+roi['height']):
            owner=u.GetAncestor(u.WindowFromPoint(w.POINT(x,y)),2)
            if owner!=client.hwnd:
                raise WindowError('occluded','Sample point belongs to another window')


def sample_wow_node(node,size=1):
    # Fresh MSS in caller's capture worker + thread-local PMv2, restored on exit.
    # Does not change the process DPI policy of the existing Tk application.
    with physical_pixels():
        client=find_wow_client()
        from wow_geometry_trace import snapshot, assert_unchanged
        before=snapshot(client,stage='before_mss_construction')
        with (getattr(mss,'MSS',None) or mss.mss)() as sct:
            monitors=[dict(m) for m in sct.monitors]
            roi=resolve_roi(client,node,size,sct.monitors)
            before.update(mss_monitors=monitors,roi=roi)
            constructed=snapshot(find_wow_client(),monitors,roi,'after_mss_construction')
            u,_=_libraries()
            _check_visible_owner(u,client,roi)
            shot=sct.grab(roi)
            after_client=find_wow_client()
            after=snapshot(after_client,[dict(m) for m in sct.monitors],roi,'after_grab')
            assert_unchanged(before,after,original_equal=after_client==client,stages=[constructed])
            _check_visible_owner(u,client,roi)
            pixels=[tuple(shot.pixel(x,y)) for y in range(size) for x in range(size)]
            screen=wow_client_to_screen(client,node['x'],node['y'])
            return pixels,{'coordinate_mode':'wow_client','node_coordinate':[node['x'],node['y']],
                           'screen_coordinate':list(screen),'client':client.to_dict(),
                           'dpi_context':'verified_thread_per_monitor_v2'}
