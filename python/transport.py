"""Bounded asynchronous UDP JSON transport. No pyserial; no Tk calls in worker."""
import ipaddress
import json
import queue
import socket
import threading
import time
from types import SimpleNamespace
from pathlib import Path
from datetime import datetime
import os
import uuid
import sys

class TxBytes(bytes):
    """Local provenance only; buffer/wire bytes are unchanged."""
    def __new__(cls, value, source_node, context):
        obj=super().__new__(cls,value)
        obj.source_node=source_node;obj.context=dict(context);obj.tx_id=uuid.uuid4().hex
        return obj

class ESP32Controller:
    def __init__(self, host="", port=8888, queue_size=64, output_mode='normal'):
        if output_mode not in ('normal','dry_run'):raise ValueError('Unknown output_mode')
        self._output_mode=output_mode
        self.dry_diagnostics=None
        self.host = host
        self.port = port
        self.queue_size = queue_size
        self.last_error = ""
        self._events = queue.Queue(maxsize=256)
        self._session = None
        self._tx_lock = threading.Lock()
        self._thread = None
        self.evidence_path = Path(__file__).resolve().parent / "diagnostics" / "udp_tx_runtime.jsonl"
        self.evidence_context = {}
        self.evidence_error = None
        self._evidence_queue = queue.Queue(maxsize=2048)
        self._evidence_thread = None
        self._evidence_stop = threading.Event()

    @property
    def output_mode(self):return self._output_mode

    def set_output_mode(self,mode):
        if mode not in ('normal','dry_run'):raise ValueError('Unknown output_mode')
        if mode==self._output_mode:return
        if self._output_mode=='dry_run':raise RuntimeError('Dry output is sticky; cannot switch to normal in this instance')
        if self._session is not None or (self._thread and self._thread.is_alive()):
            raise RuntimeError('Cannot change output mode while UDP session exists')
        self._output_mode=mode

    def _transmit_packet(self,sock,payload,destination,source_node=None):
        """Single final wire boundary, INCLUDING disconnect release_all."""
        if self.output_mode=='dry_run':
            if not isinstance(payload,TxBytes):payload=TxBytes(payload,source_node or 'UNSPECIFIED',self.evidence_context)
            accepted=self.dry_diagnostics is not None and self.dry_diagnostics.block_payload(payload,source_node)
            return len(payload) if accepted else 0
        tx_id=self._record_tx(payload,destination,source_node)
        try:
            sent=sock.sendto(payload,destination)
            self._record_tx_result(tx_id,'sent_to_os',sent_bytes=sent)
            return sent
        except BlockingIOError:
            self._record_tx_result(tx_id,'would_block');raise
        except OSError as exc:
            self._record_tx_result(tx_id,'socket_error',error=str(exc));raise

    def _append_evidence(self, record):
        if threading.current_thread() is self._thread:
            try:self._evidence_queue.put_nowait(record)
            except queue.Full:
                self.evidence_error='Evidence queue full; record dropped'
            return
        self._write_evidence(record)

    def _evidence_worker(self):
        while not self._evidence_stop.is_set() or not self._evidence_queue.empty():
            try:record=self._evidence_queue.get(timeout=.05)
            except queue.Empty:continue
            self._write_evidence(record)

    def _write_evidence(self, record):
        try:
            self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
            with self.evidence_path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            self._emit("tx_evidence", record=record)
        except Exception as exc:
            self.evidence_error = str(exc)
            self._emit("error", message="UDP 證據寫入失敗：" + str(exc))

    def _record_tx(self, payload, destination, source_node=None):
        # Called immediately before sendto with the exact same bytes object.
        raw = bytes(payload)
        try:
            command = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            command = None
        record = {"event":"UDP_TX", "timestamp":datetime.now().astimezone().isoformat(timespec="milliseconds"),
                  "pid":os.getpid(), "tx_id":getattr(payload,"tx_id",uuid.uuid4().hex),
                  "source_node":source_node or getattr(payload,"source_node","UNSPECIFIED"),
                  "context":getattr(payload,"context",dict(self.evidence_context)),
                  "command":command, "payload_raw":repr(raw), "payload_hex":raw.hex(),
                  "destination":list(destination), "stage":"before_sendto"}
        record['sendto_check_monotonic']=time.monotonic()
        schedule=record['context'].get('schedule')
        if schedule:
            record['scheduling_error_ms']=(record['sendto_check_monotonic']-schedule['deadline'])*1000
        self._append_evidence(record)
        return record["tx_id"]

    def _record_tx_result(self, tx_id, outcome, **detail):
        self._append_evidence({"event":"UDP_TX_RESULT", "timestamp":datetime.now().astimezone().isoformat(timespec="milliseconds"),
                               "pid":os.getpid(), "tx_id":tx_id, "outcome":outcome, **detail})

    @property
    def is_open(self):
        """Local UDP session exists, NOT proof that the remote device is online."""
        return self._session is not None and not self._session.stop.is_set()

    def _emit(self, kind, **data):
        try:
            self._events.put_nowait({"kind": kind, **data})
        except queue.Full:
            pass  # Bound telemetry memory; never block the network worker.

    def connect(self):
        if self.output_mode=='dry_run':
            self.last_error='DRY RUN / OUTPUT BLOCKED: UDP initialization prohibited'
            return False
        if self._thread is not None and self._thread.is_alive():
            self.last_error = "UDP 工作執行緒仍在使用或關閉中，請稍後再試"
            return False
        sock = None
        try:
            host = str(ipaddress.IPv4Address(self.host.strip()))  # No DNS lookup.
            address = ipaddress.IPv4Address(host)
            port = int(self.port)
            if address.is_unspecified or address.is_multicast or host == "255.255.255.255":
                raise ValueError("請指定 ESP32 的單一 IPv4 位址，不可廣播／多播")
            if not 1 <= port <= 65535:
                raise ValueError("Port 必須介於 1 到 65535")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            sock.bind(("0.0.0.0", 0))
            session = SimpleNamespace(sock=sock, endpoint=(host, port),
                                      tx=queue.Queue(maxsize=self.queue_size), stop=threading.Event())
            self.host, self.port = host, port
            self.poll_events(256)  # Clear stale events before starting a new session.
            self._session = session
            self.last_error = ""
            self._thread = threading.Thread(target=self._worker, args=(session,),
                                            name="esp32-udp", daemon=True)
            self._evidence_stop.clear()
            self._evidence_thread=threading.Thread(target=self._evidence_worker,name='udp-evidence',daemon=False)
            self._evidence_thread.start()
            self._thread.start()
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            if sock is not None:
                sock.close()
            self._session = None
            self.last_error = str(exc)
            return False

    def send_command(self, command_dict, source_node=None, schedule=None):
        """Return queued byte count, NOT delivered/ACKed bytes. Never wait for I/O."""
        session = self._session
        if self.output_mode!='dry_run' and (session is None or session.stop.is_set()):
            self.last_error = "UDP 尚未初始化"
            return 0
        try:
            if not isinstance(command_dict, dict):
                raise ValueError("指令必須是 JSON dictionary")
            payload = json.dumps(command_dict, ensure_ascii=False, separators=(",", ":"),
                                 allow_nan=False).encode("utf-8")
            if len(payload) > 1024:
                raise ValueError("指令超過 1024 UTF-8 bytes")
            caller = sys._getframe(1)
            context = dict(self.evidence_context)
            if schedule is not None:context["schedule"]=dict(schedule)
            context.update(caller_file=str(Path(caller.f_code.co_filename).resolve()), caller_function=caller.f_code.co_name, caller_line=caller.f_lineno)
            del caller
            payload = TxBytes(payload, source_node or "UNSPECIFIED", context)
            if self.output_mode=='dry_run':return self._transmit_packet(None,payload,None)
            with self._tx_lock:
                if session is not self._session or session.stop.is_set():
                    self.last_error = 'UDP 已停止，指令未排入'
                    return 0
                session.tx.put_nowait(payload)
            return len(payload)
        except (ValueError, TypeError, queue.Full) as exc:
            self.last_error = "UDP 發送佇列已滿" if isinstance(exc, queue.Full) else str(exc)
            self._emit("error", message=self.last_error)
            return 0

    def poll_events(self, limit=32):
        events = []
        for _ in range(limit):
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def disconnect(self):
        """No join/sleep/socket I/O on GUI thread. Worker attempts release_all once."""
        with self._tx_lock:
            if self._session is not None:
                self._session.stop.set()
                while True:
                    try:self._session.tx.get_nowait()
                    except queue.Empty:break

    def _worker(self, session):
        pending = None
        pending_since = 0.0
        try:
            while not session.stop.is_set():
                for _ in range(4):
                    if pending is None:
                        try:
                            pending = session.tx.get_nowait()
                        except queue.Empty:
                            break
                        pending_since = time.monotonic()
                    try:
                        with self._tx_lock:
                            if session.stop.is_set():break
                            sent = self._transmit_packet(session.sock,pending,session.endpoint)
                        if sent != len(pending):
                            self._emit("error", message="UDP 封包未完整交給作業系統")
                        pending = None
                    except BlockingIOError:
                        if time.monotonic() - pending_since > 0.25:
                            self._emit("error", message="UDP 本機發送忙碌，指令未送出")
                            pending = None
                        break
                    except OSError as exc:
                        raise
                for _ in range(16):
                    try:
                        payload, source = session.sock.recvfrom(2048)
                    except BlockingIOError:
                        break
                    if source != session.endpoint:
                        continue  # Do not accept ACKs from another endpoint.
                    try:
                        reply = json.loads(payload.decode("utf-8"))
                        if not isinstance(reply, dict) or reply.get("status") not in ("ok", "error"):
                            raise ValueError("unexpected ACK shape")
                        self._emit("ack", reply=reply, received_at=time.monotonic())
                    except (UnicodeError, ValueError) as exc:
                        self._emit("error", message="無效 UDP 回覆: " + str(exc))
                session.stop.wait(0.005)
        except OSError as exc:
            self.last_error = str(exc)
            self._emit("error", message="UDP socket 錯誤: " + str(exc))
        finally:
            session.stop.set()
            try:
                # Discard unsent actions, then best-effort release. Delivery is NOT guaranteed.
                release_payload = b'{"action":"release_all"}'
                sent = self._transmit_packet(session.sock,release_payload,session.endpoint,'transport.disconnect.release_all')
            except OSError:
                pass
            session.sock.close()
            self._evidence_stop.set()
            if self._evidence_thread:self._evidence_thread.join()
            self._emit("closed")
