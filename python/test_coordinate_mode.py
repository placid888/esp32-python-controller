"""No live UDP, input, or monitor: isolated coordinate integration tests."""
from contextlib import nullcontext
import copy,json
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
from wow_window import WowClient,WindowError
from wow_sampling import resolve_roi,sample_wow_node
from detector import sample_node,DetectorWorker
from vision import GameVision
import profile_store


def client(x=100,y=200,width=500,height=500):
    return WowClient(1,2,'mock','Wow.exe',width,height,x,y,(x,y,x+width,y+height))


class Coordinates(unittest.TestCase):
    def setUp(self):
        self.node=dict(profile_store.default_nodes()['Node_Target'],enabled=True,x=32,y=277,
                       coordinate_mode='wow_client',mode='color',r=0,g=0,b=255,tolerance=20)
        self.monitors=[dict(left=0,top=0,width=1920,height=1080)]

    def test_nonzero_origin(self):
        self.assertEqual(resolve_roi(client(),self.node,1,self.monitors),dict(left=132,top=477,width=1,height=1))

    def test_negative_monitor(self):
        monitors=[dict(left=-1920,top=0,width=3840,height=1080),dict(left=-1920,top=0,width=1920,height=1080),self.monitors[0]]
        self.assertEqual(resolve_roi(client(-1000,0),self.node,1,monitors)['left'],-968)

    def test_multimonitor_gap(self):
        monitors=[dict(left=0,top=0,width=2000,height=1080),dict(left=0,top=0,width=500,height=1080),dict(left=1000,top=0,width=1000,height=1080)]
        with self.assertRaises(WindowError):resolve_roi(client(600,0),self.node,1,monitors)

    def test_client_over_desktop_but_valid_point(self):
        self.assertEqual(resolve_roi(client(0,0,1942,1106),self.node,1,self.monitors)['left'],32)

    def test_roi_beyond_desktop(self):
        n=dict(self.node,x=1930)
        with self.assertRaises(WindowError):resolve_roi(client(0,0,1942,1106),n,1,self.monitors)

    def test_bounds_and_roi_edge(self):
        for x,y,size in [(-1,0,1),(500,0,1),(0,500,1),(0,0,3)]:
            with self.subTest(x=x,y=y,size=size),self.assertRaises(WindowError):
                resolve_roi(client(),dict(self.node,x=x,y=y),size,self.monitors)

    def test_legacy_sample_unchanged(self):
        v=Mock(spec=['get_region_rgb']);v.get_region_rgb.return_value=[(0,0,255)]
        n=dict(self.node);n.pop('coordinate_mode')
        match,detail=sample_node(v,n)
        self.assertTrue(match);v.get_region_rgb.assert_called_once_with(32,277,1)
        self.assertNotIn('coordinate_mode',detail)
        n['coordinate_mode']='desktop_absolute'
        self.assertEqual(sample_node(v,n),(match,detail))

    def test_client_does_not_use_legacy_or_batch_pixels(self):
        v=Mock();v.get_node_pixels.return_value=([(0,0,255)],{'coordinate_mode':'wow_client'})
        self.assertTrue(sample_node(v,self.node,pixels=[(255,0,0)])[0])
        v.get_region_rgb.assert_not_called()

    def test_legacy_config_stays_byte_equivalent(self):
        p=Path(__file__).with_name('config.json');original=json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual(original,profile_store.disk_document(profile_store.read(p)))

    def test_mode_validation_and_roundtrip(self):
        profile_store.validate_node(self.node)
        for invalid in ['bogus',None]:
            with self.assertRaises(ValueError):profile_store.validate_node(dict(self.node,coordinate_mode=invalid))
        flat={'nodes':profile_store.default_nodes()};flat['nodes']['Node_Target'].update(self.node)
        migrated=profile_store.migrate(flat)
        self.assertEqual(migrated['profiles']['Default']['nodes']['Node_Target']['coordinate_mode'],'wow_client')

    def test_no_relative_batch(self):
        v=GameVision.__new__(GameVision);v.sct=Mock()
        self.assertEqual(v.capture_nodes({'a':self.node}),{})
        v.sct.grab.assert_not_called()

    def test_sampling_failure_propagates_and_no_fallback(self):
        v=Mock();v.get_node_pixels.side_effect=WindowError('minimized','mock')
        with self.assertRaises(WindowError):sample_node(v,self.node)
        v.get_region_rgb.assert_not_called()

    def test_worker_error_stops_before_sender(self):
        for code in ['not_found','multiple_candidates','minimized','invalid_client','out_of_bounds','dpi_unverified','roi_not_capturable']:
            with self.subTest(code=code):
                nodes=profile_store.default_nodes();nodes['Node_Target'].update(self.node)
                sender=Mock();v=Mock();v.get_node_pixels.side_effect=WindowError(code,'mock')
                worker=DetectorWorker(nodes,sender,lambda:v,hunter_mark_mode='pre_combat')
                worker.run()
                sender.assert_not_called();self.assertTrue(worker.stop_event.is_set())
                self.assertIsNone(worker.opener.pending);self.assertFalse(worker.brain.pending)

    def test_real_sampling_path_with_fake_mss(self):
        shot=Mock();shot.pixel.return_value=(0,0,255)
        sct=Mock();sct.monitors=self.monitors;sct.grab.return_value=shot
        sct.__enter__=Mock(return_value=sct);sct.__exit__=Mock(return_value=False)
        with patch('wow_sampling.physical_pixels',return_value=nullcontext()), \
             patch('wow_sampling.find_wow_client',return_value=client()), \
             patch('wow_sampling.mss.MSS',return_value=sct), \
             patch('wow_geometry_trace.snapshot',return_value={'client':client().to_dict()}), \
             patch('wow_sampling._libraries',return_value=(None,None)), \
             patch('wow_sampling._check_visible_owner'):
            pixels,meta=sample_wow_node(self.node)
        self.assertEqual(pixels,[(0,0,255)])
        self.assertEqual(meta['screen_coordinate'],[132,477])
        sct.grab.assert_called_once_with(dict(left=132,top=477,width=1,height=1))


if __name__=='__main__':unittest.main(verbosity=2)
