"""Process-local diagnostic socket guard. Never changes another process/network."""
import socket,threading

class OutputBypassError(RuntimeError):pass

class ProcessOutputGuard:
    def __init__(self):self.attempts=[];self.originals={};self.lock=threading.Lock()
    def install(self):
        if self.originals:return self
        for name in ('sendto','send','sendall','sendmsg'):
            if not hasattr(socket.socket,name):continue
            original=getattr(socket.socket,name)
            def blocked(sock,*args,_name=name,**kwargs):
                with self.lock:self.attempts.append({'method':_name,'thread':threading.get_ident()})
                raise OutputBypassError('OUTPUT BLOCKED: unexpected socket.'+_name)
            self.originals[name]=(original,blocked);setattr(socket.socket,name,blocked)
        return self
    def check(self):
        if self.attempts:raise OutputBypassError('Socket bypass attempt latched; stop diagnostic')
        for name,(_,wrapper) in self.originals.items():
            if getattr(socket.socket,name) is not wrapper:raise OutputBypassError('Socket output guard was replaced')
    def close(self):
        # For isolated tests only; production dry GUI keeps guard until process exit.
        for name,(original,wrapper) in self.originals.items():
            if getattr(socket.socket,name) is wrapper:setattr(socket.socket,name,original)
        self.originals={}

_guard=None
def install_process_output_guard():
    global _guard
    if _guard is None:_guard=ProcessOutputGuard().install()
    return _guard
