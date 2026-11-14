import mss
import numpy as np
import time

class GameVision:
    """
    這是系統的「視覺引擎」。
    你可以把它想像成一個拿著超高速放大鏡的觀察員，專門幫你盯著螢幕上的特定像素看。
    """
    
    def __init__(self):
        # 初始化 mss 截圖工具，這就像是幫我們的觀察員準備好一台高速相機
        self.sct = mss.mss()

    def get_pixel_color(self, x, y):
        """
        這個函式的目的是獲取螢幕上「某一個特定點 (x, y)」的顏色。
        為了達到極致的速度，我們不是把整個螢幕拍下來再找，
        而是直接指定一個 1x1 像素的「極小範圍」進行拍攝。
        """
        # 定義截圖範圍：左上角是 (x, y)，寬度 1 像素，高度 1 像素
        monitor = {"top": y, "left": x, "width": 1, "height": 1}
        
        # 拍下這個 1x1 的小畫面
        img = self.sct.grab(monitor)
        
        # 將抓下來的畫面轉換成 numpy 矩陣，方便我們提取顏色數字
        # mss 抓下來的顏色順序預設是 BGRA (藍, 綠, 紅, 透明度)
        raw_pixels = np.array(img)
        
        # 取出第一個（也是唯一一個）像素的顏色數值
        # raw_pixels[0][0] 代表第 0 列、第 0 行的像素
        b, g, r, a = raw_pixels[0][0]
        
        # 回傳人類比較習慣的 RGB 順序 (紅, 綠, 藍)
        return (r, g, b)

    def get_region_rgb(self, x, y, size=1):
        # Screen edge coordinates are clamped to the virtual desktop.
        desktop=self.sct.monitors[0]
        left=max(desktop['left'],min(x-size//2,desktop['left']+desktop['width']-size))
        top=max(desktop['top'],min(y-size//2,desktop['top']+desktop['height']-size))
        shot=self.sct.grab({'left':left,'top':top,'width':size,'height':size})
        # MSS BGRA -> RGB exactly once. No OpenCV/channel-name assumptions.
        return [(int(r),int(g),int(b)) for b,g,r,a in np.asarray(shot).reshape(-1,4)]

    def capture_nodes(self, nodes):
        # One BitBlt for enabled skill ROIs instead of one screenshot per pixel.
        # wow_client nodes are sampled by get_node_pixels under their own verified
        # DPI/identity scope. Never batch their relative coordinates as desktop XY.
        nodes={name:n for name,n in nodes.items() if n.get('coordinate_mode','desktop_absolute')!='wow_client'}
        if not nodes:return {}
        bounds=self.sct.monitors[0];rois={}
        for name,n in nodes.items():
            size={'single_pixel':1,'3x3':3,'5x5':5}[n.get('sample_mode','single_pixel')]
            x=max(bounds['left'],min(n['x']-size//2,bounds['left']+bounds['width']-size))
            y=max(bounds['top'],min(n['y']-size//2,bounds['top']+bounds['height']-size))
            rois[name]=(x,y,size)
        left=min(r[0] for r in rois.values());top=min(r[1] for r in rois.values())
        right=max(x+z for x,y,z in rois.values());bottom=max(y+z for x,y,z in rois.values())
        frame=np.asarray(self.sct.grab({'left':left,'top':top,'width':right-left,'height':bottom-top}))
        return {name:[(int(r),int(g),int(b)) for b,g,r,a in frame[y-top:y-top+z,x-left:x-left+z].reshape(-1,4)] for name,(x,y,z) in rois.items()}

    def get_node_pixels(self, node, size=1):
        mode=node.get('coordinate_mode','desktop_absolute')
        if mode=='desktop_absolute':
            return self.get_region_rgb(node['x'],node['y'],size),{}
        if mode!='wow_client':raise ValueError('Unknown coordinate_mode')
        from wow_sampling import sample_wow_node
        return sample_wow_node(node,size)

    def close(self):
        self.sct.close()

    def is_color_match(self, x, y, target_r, target_g, target_b, tolerance=15):
        """
        這個函式用來判斷「某個座標的顏色，是不是我們想要的顏色」。
        為什麼需要 tolerance (容差)？
        因為遊戲裡的 UI 可能會有半透明、反光、或是稍微的漸層，
        如果要求顏色「100% 完全一樣」很容易誤判，所以我們容許一點點誤差。
        """
        # 先取得目前該座標的真實顏色
        r, g, b = self.get_pixel_color(x, y)
        
        # 檢查紅色、綠色、藍色是否都在「目標顏色 ± 容差」的範圍內
        # abs() 是絕對值，用來計算兩個數字差多少
        r_match = abs(r - target_r) <= tolerance
        g_match = abs(g - target_g) <= tolerance
        b_match = abs(b - target_b) <= tolerance
        
        # 只有當 R、G、B 三個顏色都符合條件時，才回傳 True (匹配成功)
        if r_match and g_match and b_match:
            return True
        else:
            return False

# --- 測試區塊 ---
# 這裡用來讓你獨立測試「眼睛」有沒有正常運作。
# 當你直接執行 python vision.py 時，它會幫你捕捉滑鼠當前位置的顏色。
if __name__ == "__main__":
    # 額外引入 pyautogui 只為了在這個測試裡獲取你目前的滑鼠座標
    # 實戰中我們不會用到 pyautogui，因為它太慢了
    try:
        import pyautogui
    except ImportError:
        print("若要執行測試，請先安裝 pyautogui (pip install pyautogui)")
        exit()

    vision = GameVision()
    print("啟動視覺測試！請移動你的滑鼠，觀察抓到的顏色...")
    print("按 Ctrl+C 可以結束測試。")
    
    try:
        while True:
            # 獲取滑鼠目前的 X, Y 座標
            mouse_x, mouse_y = pyautogui.position()
            
            # 呼叫我們的視覺引擎，去看滑鼠指著的地方是什麼顏色
            r, g, b = vision.get_pixel_color(mouse_x, mouse_y)
            
            # 在終端機印出結果，\r 是為了讓下一行覆蓋上一行，畫面看起來比較乾淨
            print(f"游標座標 ({mouse_x:>4}, {mouse_y:>4}) 的顏色為 -> R:{r:>3} G:{g:>3} B:{b:>3}", end="\r")
            
            # 稍微休息一下，避免終端機洗畫面太快
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n測試結束！")
