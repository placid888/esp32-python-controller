import pyautogui
import mss
import numpy as np
import time

def main():
    sct = mss.mss()
    print("=== 戰術座標採集器已啟動 ===")
    print("請將滑鼠移動到遊戲畫面中的關鍵位置（如血條、技能圖示）。")
    print("按 Ctrl+C 結束採集。\n")
    try:
        while True:
            x, y = pyautogui.position()
            monitor = {"top": y, "left": x, "width": 1, "height": 1}
            img = sct.grab(monitor)
            b, g, r, _ = np.array(img)[0][0]
            print(f"📍 座標 (X:{x:>4}, Y:{y:>4})  🎨 顏色 (R:{r:>3}, G:{g:>3}, B:{b:>3})", end="\r")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n採集結束！")

if __name__ == '__main__':
    main()
