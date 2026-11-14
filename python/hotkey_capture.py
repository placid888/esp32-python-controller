"""Windows global F8; worker owns its message loop and MSS instance, never Tk."""
import ctypes
import os
import queue
import threading
import time
from ctypes import wintypes

WM_HOTKEY=0x0312
WM_QUIT=0x0012
VK_F8=0x77
MOD_NOREPEAT=0x4000
HOTKEY_ID=0x7b12

class F8Capture:
    def __init__(self,capture=None,hotkeys=None):
        self.hotkeys=dict(hotkeys) if hotkeys is not None else {HOTKEY_ID:('F8',VK_F8,'capture')}
        self.events=queue.Queue(maxsize=32)
        self._capture=capture
        self._lock=threading.Lock()
        self._context=None
        self._stop=threading.Event()
        self._thread=None
        self._tid=0
    @property
    def alive(self):return self._thread is not None and self._thread.is_alive()
    def set_context(self,context):
        with self._lock:self._context=context
    def _emit(self,event):
        try:self.events.put_nowait(event)
        except queue.Full:
            try:self.events.get_nowait()
            except queue.Empty:pass
            try:self.events.put_nowait(event)
            except queue.Full:pass
    def start(self,context):
        if self.alive:return False
        if os.name!='nt':
            self._emit({'kind':'error','message':'F8 全域採集目前只支援 Windows。'});return False
        while True:
            try:self.events.get_nowait()
            except queue.Empty:break
        self.set_context(context);self._stop.clear()
        self._thread=threading.Thread(target=self._run,name='F8-capture',daemon=True)
        self._thread.start();return True
    def stop(self):
        self.set_context(None);self._stop.set()
        tid=self._tid
        if tid and os.name=='nt':
            user=ctypes.WinDLL('user32',use_last_error=True)
            user.PostThreadMessageW.argtypes=[wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
            user.PostThreadMessageW.restype=wintypes.BOOL
            user.PostThreadMessageW(tid,WM_QUIT,0,0)
    def poll(self):
        result=[]
        for _ in range(32):
            try:result.append(self.events.get_nowait())
            except queue.Empty:break
        return result
    def _run(self):
        user=ctypes.WinDLL('user32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        user.RegisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.UINT,wintypes.UINT];user.RegisterHotKey.restype=wintypes.BOOL
        user.UnregisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int];user.UnregisterHotKey.restype=wintypes.BOOL
        user.PeekMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT,wintypes.UINT];user.PeekMessageW.restype=wintypes.BOOL
        user.GetMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT];user.GetMessageW.restype=ctypes.c_int
        user.GetCursorPos.argtypes=[ctypes.POINTER(wintypes.POINT)];user.GetCursorPos.restype=wintypes.BOOL
        kernel.GetCurrentThreadId.restype=wintypes.DWORD
        registered=[];sct=None
        try:
            msg=wintypes.MSG();user.PeekMessageW(ctypes.byref(msg),None,0,0,0)
            self._tid=kernel.GetCurrentThreadId()
            if self._stop.is_set():return
            for ident,(label,vk,kind) in self.hotkeys.items():
                if not user.RegisterHotKey(None,ident,MOD_NOREPEAT,vk):
                    code=ctypes.get_last_error();raise OSError(code,'無法註冊 '+label+'；可能已被其他程式占用。')
                registered.append(ident)
            if self._capture is None and any(spec[2]=='capture' for spec in self.hotkeys.values()):
                import mss
                sct=(getattr(mss,"MSS",None) or mss.mss)()  # MSS belongs to its worker.
            self._emit({'kind':'ready'})
            while not self._stop.is_set():
                result=user.GetMessageW(ctypes.byref(msg),None,0,0)
                if result==0:break
                if result==-1:raise ctypes.WinError(ctypes.get_last_error())
                if msg.message!=WM_HOTKEY or msg.wParam not in self.hotkeys:continue
                with self._lock:context=self._context
                label,vk,kind=self.hotkeys[msg.wParam]
                if self._stop.is_set():continue
                if kind!='capture':
                    self._emit({'kind':'calibration_hotkey','key':label,'type':kind,'context':context,'timestamp':time.monotonic()})
                    continue
                if context is None:continue
                try:
                    # Extended GUI context: epoch/profile/node/class/spec/mode.
                    # Legacy test/listener contexts remain desktop_absolute.
                    mode=context[5] if isinstance(context,(tuple,list)) and len(context)>5 else 'desktop_absolute'
                    metadata={'coordinate_mode':mode}
                    if mode=='wow_client':
                        from wow_calibration import capture_wow_calibration
                        x,y,rgb,metadata=capture_wow_calibration()
                    elif mode=='desktop_absolute':
                        if self._capture is not None:x,y,rgb=self._capture()
                        else:
                            point=wintypes.POINT()
                            if not user.GetCursorPos(ctypes.byref(point)):raise ctypes.WinError(ctypes.get_last_error())
                            x,y=point.x,point.y
                            rgb=sct.grab({'left':x,'top':y,'width':1,'height':1}).pixel(0,0)
                    else:raise ValueError('Invalid coordinate_mode; F8 sample rejected')
                    if not self._stop.is_set():self._emit({'kind':'capture','context':context,'x':int(x),'y':int(y),'rgb':tuple(int(c) for c in rgb),'timestamp':time.monotonic(),**metadata})
                except Exception as exc:self._emit({'kind':'capture_error','context':context,'message':str(exc)})
        except Exception as exc:self._emit({'kind':'error','message':str(exc)})
        finally:
            try:
                if sct is not None:sct.close()
            finally:
                for ident in registered:user.UnregisterHotKey(None,ident)
                self._tid=0;self._emit({'kind':'stopped'})
