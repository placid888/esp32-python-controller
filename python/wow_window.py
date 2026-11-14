"""Read-only WoW window geometry; no input, hooks, or process-memory access."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import ctypes as c
from ctypes import wintypes as w
import os


class WindowError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WowClient:
    hwnd: int
    pid: int
    title: str
    process_image: str
    client_width: int
    client_height: int
    client_origin_screen_x: int
    client_origin_screen_y: int
    window_rect: tuple

    def to_dict(self):
        return asdict(self)


def _libraries():
    if os.name != 'nt':
        raise WindowError('unsupported_platform', 'Windows is required')
    u = c.WinDLL('user32', use_last_error=True)
    k = c.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'IsWindowVisible': ([w.HWND], w.BOOL),
        'IsWindow': ([w.HWND], w.BOOL),
        'IsIconic': ([w.HWND], w.BOOL),
        'GetWindowTextLengthW': ([w.HWND], c.c_int),
        'GetWindowTextW': ([w.HWND, w.LPWSTR, c.c_int], c.c_int),
        'GetWindowThreadProcessId': ([w.HWND, c.POINTER(w.DWORD)], w.DWORD),
        'GetClientRect': ([w.HWND, c.POINTER(w.RECT)], w.BOOL),
        'GetWindowRect': ([w.HWND, c.POINTER(w.RECT)], w.BOOL),
        'ClientToScreen': ([w.HWND, c.POINTER(w.POINT)], w.BOOL),
        'SetThreadDpiAwarenessContext': ([c.c_void_p], c.c_void_p),
    }
    for name, (args, result) in signatures.items():
        try:
            fn = getattr(u, name)
        except AttributeError:
            raise WindowError('dpi_api_unavailable', name)
        fn.argtypes, fn.restype = args, result
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
    k.QueryFullProcessImageNameW.restype = w.BOOL
    k.CloseHandle.argtypes, k.CloseHandle.restype = [w.HANDLE], w.BOOL
    return u, k


@contextmanager
def physical_pixels():
    """Thread-local PMv2 only; restore on exit, never change Tk process DPI.

    Use on a standalone diagnostic/capture worker, not a Tk UI thread. Enter
    before MSS construction and keep active through Win32 geometry and capture.
    MSS may set its own process default; we intentionally run in another process.
    """
    u, _ = _libraries()
    previous = u.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    if not previous:
        raise WindowError('dpi_setup_failed', str(c.get_last_error()))
    try:
        u.GetThreadDpiAwarenessContext.argtypes=[]
        u.GetThreadDpiAwarenessContext.restype=c.c_void_p
        u.AreDpiAwarenessContextsEqual.argtypes=[c.c_void_p,c.c_void_p]
        u.AreDpiAwarenessContextsEqual.restype=w.BOOL
        if not u.AreDpiAwarenessContextsEqual(u.GetThreadDpiAwarenessContext(),c.c_void_p(-4)):
            raise WindowError('dpi_unverified','Thread PMv2 context could not be verified')
        yield
    finally:
        if not u.SetThreadDpiAwarenessContext(previous):
            raise WindowError('dpi_restore_failed', str(c.get_last_error()))


def _image(k, pid):
    # Limited metadata-query access only. No VM_READ, ReadProcessMemory or injection.
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        size = w.DWORD(32768)
        buf = c.create_unicode_buffer(size.value)
        return buf.value if k.QueryFullProcessImageNameW(handle, 0, buf, c.byref(size)) else None
    finally:
        k.CloseHandle(handle)


def validate_candidates(candidates):
    if not candidates:
        raise WindowError('not_found', 'No verified WoW window')
    if len(candidates) != 1:
        raise WindowError('multiple_candidates', f'{len(candidates)} verified WoW windows; refusing to choose')
    return candidates[0]


def _geometry(u, hwnd, pid, title, image):
    if not u.IsWindow(hwnd) or not u.IsWindowVisible(hwnd):
        raise WindowError('window_unavailable', 'Window disappeared or is hidden')
    if u.IsIconic(hwnd):
        raise WindowError('minimized', 'WoW is minimized')
    rect, outer, point = w.RECT(), w.RECT(), w.POINT(0, 0)
    if not u.GetClientRect(hwnd, c.byref(rect)) or not u.ClientToScreen(hwnd, c.byref(point)):
        raise WindowError('geometry_failed', str(c.get_last_error()))
    if not u.GetWindowRect(hwnd, c.byref(outer)):
        raise WindowError('geometry_failed', 'GetWindowRect failed')
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise WindowError('invalid_client', f'{width}x{height}')
    return WowClient(int(hwnd), pid, title, image, width, height, point.x, point.y,
                     (outer.left, outer.top, outer.right, outer.bottom))


def find_wow_client(expected_image=None):
    u, k = _libraries()
    found, errors = [], []
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

    @callback_type
    def visit(hwnd, unused):
        try:
            if not u.IsWindowVisible(hwnd):
                return True
            length = u.GetWindowTextLengthW(hwnd)
            buf = c.create_unicode_buffer(length + 1)
            u.GetWindowTextW(hwnd, buf, len(buf))
            title = buf.value
            pid = w.DWORD()
            u.GetWindowThreadProcessId(hwnd, c.byref(pid))
            image = _image(k, pid.value)
            title_hint = '魔獸世界' in title or 'world of warcraft' in title.lower()
            if image is None:
                if title_hint:
                    errors.append('Cannot verify process image for WoW-titled window')
                return True
            if os.path.basename(image).lower() != 'wow.exe':
                return True
            if expected_image and os.path.normcase(os.path.abspath(image)) != os.path.normcase(os.path.abspath(expected_image)):
                return True
            found.append((hwnd, pid.value, title, image))
        except Exception as exc:
            errors.append(str(exc))
        return True

    u.EnumWindows.argtypes, u.EnumWindows.restype = [callback_type, w.LPARAM], w.BOOL
    if not u.EnumWindows(visit, 0):
        raise WindowError('enumeration_failed', str(c.get_last_error()))
    if errors:
        raise WindowError('identity_unverified', '; '.join(errors))
    return _geometry(u, *validate_candidates(found))


def wow_client_to_screen(client, x, y):
    """Pure conversion on a validated geometry snapshot; no OS calls or clamping."""
    if type(x) is not int or type(y) is not int:
        raise WindowError('invalid_coordinate', 'Integer physical client pixels required')
    if not (0 <= x < client.client_width and 0 <= y < client.client_height):
        raise WindowError('out_of_bounds', f'({x},{y}) outside {client.client_width}x{client.client_height}')
    return client.client_origin_screen_x + x, client.client_origin_screen_y + y


def wow_screen_to_client(client,x,y):
    """Pure inverse using a fresh physical-pixel geometry snapshot; no fallback."""
    if type(x) is not int or type(y) is not int:
        raise WindowError('invalid_coordinate','Integer desktop pixels required')
    cx,cy=x-client.client_origin_screen_x,y-client.client_origin_screen_y
    wow_client_to_screen(client,cx,cy)  # validates the full inverse point
    return cx,cy
