"""Read-only F8 client calibration on the capture worker, never the Tk thread."""
import ctypes as c
from ctypes import wintypes as w
import mss
from wow_window import physical_pixels,find_wow_client,wow_screen_to_client,WindowError,_libraries
from wow_sampling import resolve_roi,_check_visible_owner


def calibration_coordinates(mode,x,y,client=None):
    if mode=='desktop_absolute':return x,y
    if mode!='wow_client':raise WindowError('invalid_coordinate_mode','Unknown calibration mode')
    if client is None:raise WindowError('not_found','Verified WoW geometry required')
    return wow_screen_to_client(client,x,y)


def capture_wow_calibration():
    with physical_pixels():
        client=find_wow_client()
        from wow_geometry_trace import snapshot,assert_unchanged
        before=snapshot(client,stage='calibration_before_mss')
        u,_=_libraries()
        u.GetCursorPos.argtypes,u.GetCursorPos.restype=[c.POINTER(w.POINT)],w.BOOL
        u.ScreenToClient.argtypes,u.ScreenToClient.restype=[w.HWND,c.POINTER(w.POINT)],w.BOOL
        cursor=w.POINT()
        if not u.GetCursorPos(c.byref(cursor)):
            raise WindowError('cursor_failed',str(c.get_last_error()))
        sx,sy=cursor.x,cursor.y
        x,y=calibration_coordinates('wow_client',sx,sy,client)
        os_point=w.POINT(sx,sy)
        if not u.ScreenToClient(client.hwnd,c.byref(os_point)) or (os_point.x,os_point.y)!=(x,y):
            raise WindowError('conversion_mismatch','ScreenToClient disagrees with inverse geometry')
        with (getattr(mss,'MSS',None) or mss.mss)() as sct:
            roi=resolve_roi(client,{'x':x,'y':y},1,sct.monitors)
            before.update(mss_monitors=[dict(m) for m in sct.monitors],roi=roi)
            _check_visible_owner(u,client,roi)
            rgb=tuple(int(v) for v in sct.grab(roi).pixel(0,0))
            after_client=find_wow_client()
            assert_unchanged(before,snapshot(after_client,[dict(m) for m in sct.monitors],roi,'calibration_after_grab'),
                             original_equal=after_client==client)
            _check_visible_owner(u,client,roi)
        return x,y,rgb,{'screen_x':sx,'screen_y':sy,'coordinate_mode':'wow_client',
                        'client_origin':[client.client_origin_screen_x,client.client_origin_screen_y]}
