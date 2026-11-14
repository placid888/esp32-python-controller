"""CLI shares the exact same independent detector used by GUI."""
import argparse,time
from pathlib import Path
from detector import DetectorWorker
from vision import GameVision
from transport import ESP32Controller
import profile_store
from mark_opener import mark_settings

def main():
    p=argparse.ArgumentParser();p.add_argument('--host');p.add_argument('--port',type=int);p.add_argument('--profile');a=p.parse_args()
    data=profile_store.read(Path(__file__).with_name('config.json'));profile=data['profiles'][a.profile or data['last_used']]
    endpoint=profile.get('udp_endpoint',{});c=ESP32Controller(a.host or endpoint.get('host',''),a.port or endpoint.get('port',8888))
    if not c.connect():raise SystemExit(c.last_error)
    worker=DetectorWorker(profile['nodes'],c.send_command,GameVision,combat_mode=profile.get('combat_mode','auto'),**mark_settings(profile));worker.start()
    try:
        while worker.thread.is_alive():
            time.sleep(.25)
            while not worker.events.empty():print(worker.events.get_nowait())
    except KeyboardInterrupt:pass
    finally:worker.stop();c.disconnect();c._thread.join()
if __name__=='__main__':main()
