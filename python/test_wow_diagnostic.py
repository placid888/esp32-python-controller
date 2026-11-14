"""Synthetic tests; no input, transport, GUI or live capture."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from types import SimpleNamespace
import numpy as np
from wow_window import WowClient, WindowError, validate_candidates, wow_client_to_screen, _geometry
from wow_vision_diagnostic import scan_regions, inspect_frame, capture_diagnostic


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.client=WowClient(1,2,'test','Wow.exe',128,100,-300,80,(0,0,0,0))

    def test_missing_and_multiple(self):
        for values,code in [([], 'not_found'),([1,2],'multiple_candidates')]:
            with self.assertRaises(WindowError) as cm: validate_candidates(values)
            self.assertEqual(cm.exception.code,code)

    def test_bounds_and_negative_desktop(self):
        self.assertEqual(wow_client_to_screen(self.client,10,20),(-290,100))
        for point in [(-1,0),(128,0),(0,100),(0,-1),(1.5,1)]:
            with self.assertRaises(WindowError):wow_client_to_screen(self.client,*point)

    def test_connected_regions_and_exact_rgb(self):
        rgb=np.zeros((100,128,3),dtype=np.uint8)
        rgb[20:46,10:36]=(0,0,255)
        rgb[20:46,66:92]=(0,255,0)
        rgb[3,3]=(0,0,255)  # isolated noise is not a block
        report=inspect_frame(self.client,rgb)
        blue=report['candidates']['blue']
        self.assertEqual(len(blue),1)
        self.assertEqual(blue[0]['bbox_client'],[10,20,36,46])
        self.assertEqual(blue[0]['center_rgb'],[0,0,255])
        self.assertEqual(blue[0]['center_screen'],[-278,112])
        self.assertEqual(len(report['aligned_pairs']),1)

    def test_threshold_and_shape(self):
        rgb=np.zeros((100,128,3),dtype=np.uint8)
        rgb[10:36,10:36]=(20,20,235)
        self.assertEqual(len(scan_regions(rgb,(0,0,255))),1)
        rgb[10:36,10:36]=(21,20,235)
        self.assertEqual(scan_regions(rgb,(0,0,255)),[])
        rgb[10:12,10:90]=(0,0,255)
        self.assertEqual(scan_regions(rgb,(0,0,255)),[])

    def test_no_transport_or_gui_import(self):
        forbidden={'socket','transport','gui','detector','mark_opener','pyautogui','profile_store'}
        for name in ['wow_window.py','wow_vision_diagnostic.py']:
            tree=ast.parse(Path(__file__).with_name(name).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    self.assertTrue(forbidden.isdisjoint(n.name.split('.')[0] for n in node.names))
                elif isinstance(node,ast.ImportFrom):
                    self.assertNotIn((node.module or '').split('.')[0],forbidden)

    def test_missing_capture_safely_fails_before_mss(self):
        with patch('wow_vision_diagnostic.physical_pixels',return_value=nullcontext()), \
             patch('wow_vision_diagnostic.find_wow_client',side_effect=WindowError('not_found','test')), \
             patch('mss.MSS') as grabber:
            with self.assertRaises(WindowError) as cm:capture_diagnostic()
            self.assertEqual(cm.exception.code,'not_found')
            grabber.assert_not_called()

    def test_invalid_point_fails_before_capture(self):
        with patch('wow_vision_diagnostic.physical_pixels',return_value=nullcontext()), \
             patch('wow_vision_diagnostic.find_wow_client',return_value=self.client), \
             patch('mss.MSS') as grabber:
            with self.assertRaises(WindowError):capture_diagnostic(points=[(128,0)])
            grabber.assert_not_called()

    def test_minimized_window_fails(self):
        api=SimpleNamespace(IsWindow=lambda h:True,IsWindowVisible=lambda h:True,IsIconic=lambda h:True)
        with self.assertRaises(WindowError) as cm:_geometry(api,1,2,'test','Wow.exe')
        self.assertEqual(cm.exception.code,'minimized')


if __name__=='__main__':unittest.main(verbosity=2)
