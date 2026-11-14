"""Synthetic geometry changes; no sockets, game input or live capture."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from wow_geometry_trace import differences,assert_unchanged
from wow_window import WindowError

def base():
    return dict(timestamp='before',client=dict(hwnd=1,pid=2,title='WoW',process_image='Wow.exe',
        client_width=1920,client_height=1080,client_origin_screen_x=0,client_origin_screen_y=0,
        window_rect=[0,0,1920,1080]),dpi_context={'raw':-4,'pmv2':True},window_dpi=144,
        foreground_hwnd=1,mss_monitors=[dict(left=0,top=0,width=1920,height=1080)],
        get_client_rect={'ok':True,'rect':[0,0,1920,1080]},
        client_to_screen={'ok':True,'point':[0,0]},dwm_extended_frame_bounds=[0,0,1920,1080],
        client_type='wow_window.WowClient',roi=dict(left=32,top=277,width=1,height=1))

class GeometryTests(unittest.TestCase):
    def test_timestamp_not_geometry(self):
        a=base();b=copy.deepcopy(a);b['timestamp']='after';assert_unchanged(a,b)
    def test_size_even_one_pixel_fails(self):self.change('client','client_width',1921,'client_size_changed')
    def test_origin(self):self.change('client','client_origin_screen_x',1,'client_origin_changed')
    def test_identity(self):self.change('client','pid',3,'window_identity_changed')
    def test_title(self):self.change('client','title','Other','window_title_changed')
    def test_outer(self):self.change('client','window_rect',[0,0,1942,1106],'window_rect_changed')
    def test_dpi_context(self):self.change(None,'dpi_context',{'raw':-2},'dpi_context_changed')
    def test_dpi(self):self.change(None,'window_dpi',96,'window_dpi_changed')
    def test_foreground(self):self.change(None,'foreground_hwnd',99,'foreground_changed')
    def test_bounds(self):self.change(None,'mss_monitors',[],'capture_bounds_changed')
    def test_snapshot_equality_not_ignored(self):
        with tempfile.TemporaryDirectory() as d,patch('wow_geometry_trace.LOG',Path(d)/'log'):
            with self.assertRaises(WindowError) as e:assert_unchanged(base(),base(),original_equal=False)
            self.assertEqual(e.exception.code,'snapshot_equality_changed')
    def test_transient_stage_change_not_ignored(self):
        stage=base();stage['dpi_context']={'raw':-2};stage['stage']='construction'
        with tempfile.TemporaryDirectory() as d,patch('wow_geometry_trace.LOG',Path(d)/'log'):
            with self.assertRaises(WindowError):assert_unchanged(base(),base(),stages=[stage])
    def change(self,group,key,value,reason):
        a=base();b=copy.deepcopy(a);b['timestamp']='after'
        (b[group] if group else b)[key]=value
        with tempfile.TemporaryDirectory() as d,patch('wow_geometry_trace.LOG',Path(d)/'log') as _:
            with self.assertRaises(WindowError) as e:assert_unchanged(a,b)
            self.assertEqual(e.exception.code,reason)
            record=json.loads((Path(d)/'log').read_text(encoding='utf-8'))
            self.assertEqual(record['before'],a);self.assertEqual(record['after'],b)

if __name__=='__main__':unittest.main(verbosity=2)
