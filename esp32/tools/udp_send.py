"""Send exactly one JSON datagram; no automatic retries (avoids duplicate HID taps)."""
import argparse
import json
import socket

def encode_command(text):
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("JSON command must be an object")
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > 1024:
        raise ValueError("command exceeds 1024 UTF-8 bytes")
    return payload

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("host", help="ESP32 LCD IPv4 address")
    parser.add_argument("command", help='JSON, e.g. {"action":"lcd_test","message":"UDP OK"}')
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    payload = encode_command(args.command)
    if args.dry_run:
        print(payload.decode("utf-8"))
        return
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.connect((args.host, args.port))
        sock.send(payload)
        try:
            reply = sock.recv(2048)
        except socket.timeout:
            raise SystemExit("No ACK: command may already have run. Do not blindly retry taps.")
    print(reply.decode("utf-8"))

if __name__ == "__main__":
    main()
