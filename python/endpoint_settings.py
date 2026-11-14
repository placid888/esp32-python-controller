"""Validated UDP endpoint persistence; preserves unrelated configuration."""
import ipaddress
import json
import profile_store

def validate(host,port):
    ip=ipaddress.IPv4Address(str(host).strip())
    if ip.is_unspecified or ip.is_multicast or str(ip)=='255.255.255.255':
        raise ValueError('請輸入 ESP32 的單一 IPv4 位址')
    if isinstance(port,bool):raise ValueError('Port 必須是 1–65535')
    port=int(str(port).strip())
    if not 1<=port<=65535:raise ValueError('Port 必須是 1–65535')
    return str(ip),port

def load(path):
    try:
        data=profile_store.active(path)['udp_endpoint']
        return validate(data['host'],data['port'])
    except (OSError,ValueError,KeyError,TypeError):return '',8888

def save(path,host,port):
    host,port=validate(host,port)
    profile_store.update_active(path, {'udp_endpoint':{'host':host,'port':port}})
    return host,port
