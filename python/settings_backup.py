"""Local verified config snapshots. No networking, input or execution of content."""
import hashlib,json,os,tempfile
from pathlib import Path
from datetime import datetime
import profile_store as store
FORMAT='wow-controller-config-backup-v1'
LIMIT=8*1024*1024

def digest(raw):return hashlib.sha256(raw).hexdigest()
def validate(raw):
    if len(raw)>LIMIT:raise ValueError('設定檔超過8MB')
    data=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data,dict) or data.get('schema_version')!=4 or not data.get('profiles'):raise ValueError('不是目前版本的控制台設定檔')
    parsed=store.migrate(data)
    from rage_rules import validate as rage_validate
    from focus_rules import validate as focus_validate
    for profile in parsed['profiles'].values():
        for character,cls in profile['classes'].items():
            for spec in cls['specs'].values():
                metadata=spec['metadata']
                if 'rage_advisory_v1' in metadata:rage_validate(metadata['rage_advisory_v1'])
                if 'focus_advisory_v1' in metadata:focus_validate(metadata['focus_advisory_v1'])
    return parsed

def create_backup(config,directory):
    raw=Path(config).read_bytes();validate(raw)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/('settings-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.wowbackup.json')
    envelope={'format':FORMAT,'created':datetime.now().astimezone().isoformat(),'sha256':digest(raw),'config_text':raw.decode('utf-8')}
    with path.open('x',encoding='utf-8') as f:
        json.dump(envelope,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    assert read_backup(path)==raw
    return path

def read_backup(path):
    path=Path(path)
    if path.stat().st_size>LIMIT*2:raise ValueError('備份檔過大')
    envelope=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(envelope,dict) or envelope.get('format')!=FORMAT:raise ValueError('請選擇由本控制台建立的 .wowbackup.json 檔案')
    raw=envelope['config_text'].encode('utf-8')
    if digest(raw)!=envelope.get('sha256'):raise ValueError('備份完整性檢查失敗；檔案可能已修改')
    validate(raw);return raw

def replace_config(path,raw,expected_hash):
    path=Path(path);validate(raw)
    if digest(path.read_bytes())!=expected_hash:raise ValueError('設定檔已變更，請重新操作')
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.restore-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        if digest(path.read_bytes())!=expected_hash:raise ValueError('設定檔已變更，未覆寫')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def restore(config,backup,directory,expected_hash,expected_backup_hash=None):
    raw=read_backup(backup)
    if expected_backup_hash is not None and digest(raw)!=expected_backup_hash:raise ValueError('選取的備份已變更，請重新選取')
    if digest(Path(config).read_bytes())!=expected_hash:raise ValueError('設定檔已變更，請重新操作')
    safety=create_backup(config,directory)
    replace_config(config,raw,expected_hash)
    return safety
