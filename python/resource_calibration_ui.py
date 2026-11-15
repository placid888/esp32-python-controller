"""Evidence-backed display only; never grants combat or calibration permission."""
import hashlib,inspect
from pathlib import Path
from tkinter import ttk
WARRIOR_ESTIMATOR_HASH = 'ab9498dee81def59e54bf5bdb5fd1f3caaa146961b9f55ebe89b35c3cc80e43e'

FOCUS_FULL_IDENTITY=('獵人','hunter','beast_mastery')
FOCUS_FULL_CAPTURE_HASH='f1da78ca3fcddc2c0ce1e9c0a2a66a7235fdc12a9abb2a393dca0432749e905f'
FOCUS_FULL_CONFIG_HASH='f2293e583e651b6f0e51bcf03c889ce7f21217b6ae0d6caa3976c54c11df567f'

def focus_full_sample_applies(identity,config_path):
    if tuple(identity or ())!=FOCUS_FULL_IDENTITY or config_path is None:return False
    try:
        capture=Path(__file__).with_name('focus_monitor.py')
        return (hashlib.sha256(capture.read_bytes()).hexdigest()==FOCUS_FULL_CAPTURE_HASH
                and hashlib.sha256(Path(config_path).read_bytes()).hexdigest()==FOCUS_FULL_CONFIG_HASH
                and hashlib.sha256(capture.with_name('focus_digits.py').read_bytes()).hexdigest()=='ddc52796ee621fce3cd7c2ad90a086a5a24ea571ba3cf5dc192579c4e8bb87f3'
                and hashlib.sha256(capture.with_name('templates.json').read_bytes()).hexdigest()=='9f05de074229e1669e2a66040b8c25ec74e6fbfbf6c949525831ca267b49e51b'
                and hashlib.sha256(capture.with_name('wow_window.py').read_bytes()).hexdigest()=='aa01f25c2b61777aa0fc8f7279eab770e5775d31d3c0b52dd8f82733f6adc168')
    except OSError:return False

def status_text(character, *, identity=None, config_path=None):
    if character == 'warrior':
        from rage_monitor import estimate
        fingerprint=hashlib.sha256(inspect.getsource(estimate).encode()).hexdigest()
        if fingerprint == WARRIOR_ESTIMATOR_HASH:
            return ('怒氣讀值驗證：已完成（2026/11/15）',
                    '已核對100、70、48怒氣截圖，誤差不超過1。僅適用 Warrior Clean／1920×1080；移動資源條或改解析度需重校。')
        return ('怒氣讀值驗證：需重新校準','讀取演算法已變更，先前驗證不再適用。')
    if character == 'hunter':
        if focus_full_sample_applies(identity,config_path):
            return ('集中值讀值驗證：已完成新版實機核對（2026/11/15）',
                    '新版實測70次，讀值11～100；數字與條長差0～1，人工抽查4幀一致，已核對消耗與恢復。不同步拒絕已通過離線測試，本輪未觸發。僅限本次獵人／野獸控制、Hunter Clean／1920×1080與版本；不是全數值校準，移動資源條或更改版面需重測。')
        return ('集中值讀值驗證：待實機校準','尚無此設定版本的完整讀值驗證；能讀到數字不等於動態校準完成。')
    return ('資源讀值驗證：尚未設定','請先選擇職業。')

def add_status(parent,character,wraplength=520,identity=None,config_path=None):
    frame=ttk.Frame(parent);frame.pack(fill='x',pady=(6,8))
    title=ttk.Label(frame,font=('Microsoft JhengHei UI',10,'bold'),wraplength=wraplength);title.pack(anchor='w')
    detail=ttk.Label(frame,wraplength=wraplength);detail.pack(anchor='w',pady=(3,0))
    ttk.Label(frame,text='技能整合：未完成（冷卻／距離／可用性）；此功能不自動按鍵。',wraplength=wraplength).pack(anchor='w',pady=(3,0))
    def refresh():
        if not frame.winfo_exists():return
        selected=identity() if callable(identity) else identity
        heading,body=status_text(character() if callable(character) else character,identity=selected,config_path=config_path)
        title.configure(text=heading);detail.configure(text=body)
        frame.after(750,refresh)
    refresh()
    return frame
