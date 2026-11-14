"""Isolated mode/queue tests. No child GUI, network or game input is launched."""
import io
import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import output_mode_session as modes
from transport import ESP32Controller


class ModeTests(unittest.TestCase):
    def test_default_and_restart_are_dry(self):
        self.assertEqual(modes.startup_mode(['START_GUI.pyw']), 'dry_run')
        self.assertEqual(modes.startup_mode(['gui.py', '--normal']), 'dry_run')
        self.assertEqual(modes.startup_mode(['gui.py', modes.FLAG], io.TextIOWrapper(io.BytesIO())), 'dry_run')

    def test_explicit_one_shot_handoff(self):
        stream = io.TextIOWrapper(io.BytesIO(modes.GRANT))
        self.assertEqual(modes.startup_mode(['gui.py', modes.FLAG], stream), 'normal')
        self.assertEqual(modes.startup_mode(['gui.py', modes.FLAG], stream), 'dry_run')

    def test_invalid_grant_is_dry(self):
        self.assertEqual(modes.startup_mode(['gui.py', modes.FLAG], io.TextIOWrapper(io.BytesIO(b'no\n'))), 'dry_run')

    @patch.object(modes.subprocess, 'Popen')
    def test_normal_is_separate_process_no_socket(self, popen):
        child = popen.return_value
        modes.launch_session('normal')
        self.assertIn(modes.FLAG, popen.call_args.args[0])
        child.stdin.write.assert_called_once_with(modes.GRANT)
        child.stdin.close.assert_called_once()

    @patch.object(modes.subprocess, 'Popen')
    def test_dry_handoff_has_no_grant(self, popen):
        modes.launch_session('dry_run')
        self.assertNotIn(modes.FLAG, popen.call_args.args[0])
        popen.return_value.stdin.write.assert_not_called()

    def test_stop_cancels_unsent_queue(self):
        c = ESP32Controller()
        c._session = SimpleNamespace(stop=threading.Event(), tx=queue.Queue())
        c._session.tx.put(b'not sent')
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            c.disconnect()
        self.assertTrue(c._session.stop.is_set())
        self.assertTrue(c._session.tx.empty())

    def test_stopped_worker_only_attempts_release(self):
        c = ESP32Controller()
        session = SimpleNamespace(stop=threading.Event(), tx=queue.Queue(), sock=Mock(), endpoint=('127.0.0.1', 9999))
        session.tx.put(b'cancelled HID')
        session.stop.set()
        c._transmit_packet = Mock(return_value=24)
        c._worker(session)
        c._transmit_packet.assert_called_once_with(session.sock, b'{"action":"release_all"}', session.endpoint, 'transport.disconnect.release_all')
        session.sock.close.assert_called_once()


class GuiModeTests(unittest.TestCase):
    def app(self, mode='dry_run'):
        from gui import MacroDashboard
        app = SimpleNamespace(controller=SimpleNamespace(output_mode=mode, _thread=None, is_open=False),
            output_mode_var=Mock(), is_running=False, dry_start_after_id=None, is_tracking=False,
            root=Mock(), request_close=Mock(), profile_guard=Mock(return_value=True))
        app.output_mode_var.get.return_value = 'UDP 測試' if mode == 'dry_run' else 'Dry Run'
        return MacroDashboard, app

    @patch('gui.calibration_ui.busy', return_value=False)
    @patch('gui.messagebox.askyesno', return_value=True)
    @patch('output_mode_session.launch_session')
    def test_confirm_replaces_not_mutates_controller(self, launch, confirm, busy):
        cls, app = self.app()
        original = app.controller
        cls.change_output_mode(app)
        confirm.assert_called_once()
        launch.assert_called_once_with('normal')
        app.request_close.assert_called_once()
        self.assertIs(app.controller, original)
        self.assertEqual(original.output_mode, 'dry_run')

    @patch('gui.calibration_ui.busy', return_value=False)
    @patch('gui.messagebox.askyesno', return_value=False)
    @patch('output_mode_session.launch_session')
    def test_cancel_stays_dry(self, launch, confirm, busy):
        cls, app = self.app()
        cls.change_output_mode(app)
        launch.assert_not_called()
        app.request_close.assert_not_called()

    @patch('gui.messagebox.showwarning')
    @patch('output_mode_session.launch_session')
    def test_running_or_connected_cannot_switch(self, launch, warning):
        for field in ('is_running', 'dry_start_after_id', 'is_tracking'):
            cls, app = self.app()
            setattr(app, field, True)
            cls.change_output_mode(app)
        cls, app = self.app()
        app.controller.is_open = True
        cls.change_output_mode(app)
        self.assertEqual(warning.call_count, 4)
        launch.assert_not_called()

    @patch('gui.calibration_ui.busy', return_value=False)
    @patch('output_mode_session.launch_session', side_effect=OSError('test launch failure'))
    @patch('gui.messagebox.askyesno', return_value=True)
    @patch('gui.messagebox.showerror')
    def test_failed_handoff_keeps_current_window(self, error, confirm, launch, busy):
        cls, app = self.app()
        cls.change_output_mode(app)
        app.request_close.assert_not_called()
        error.assert_called_once()

    def test_stop_order(self):
        from gui import MacroDashboard
        calls = []
        app = SimpleNamespace(stop_loop=lambda reason:calls.append('monitor'), disconnect_hw=lambda:calls.append('UDP'))
        MacroDashboard.stop_all(app)
        self.assertEqual(calls, ['monitor', 'UDP'])


if __name__ == '__main__':
    unittest.main()
