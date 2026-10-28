from pathlib import Path
import unittest
from unittest.mock import MagicMock, Mock, patch

from network_labs.appliances.radius_session import SessionGroup, session_parent
from network_labs.appliances.runtime import RuntimeFailure


class RadiusSessionTests(unittest.TestCase):
    def group(self, events):
        group = SessionGroup.__new__(SessionGroup); group.closed = False
        group.path = MagicMock(); kill = Mock(); observed = Mock()
        observed.read_text.side_effect = events
        group.path.__truediv__.side_effect = lambda name: {'cgroup.kill': kill, 'cgroup.events': observed}[name]
        return group, kill

    def test_exit_kills_own_subtree_then_waits_for_empty_before_removing_it(self):
        group, kill = self.group(['populated 1\nfrozen 0\n', 'populated 0\nfrozen 0\n'])
        with patch('network_labs.appliances.radius_session.time.sleep'):
            self.assertFalse(group.__exit__(None, None, None))
        kill.write_text.assert_called_once_with('1')
        group.path.rmdir.assert_called_once_with(); self.assertTrue(group.closed)

    def test_failed_cleanup_never_reports_complete_or_removes_populated_group(self):
        group, kill = self.group(['populated 1\n'])
        with patch('network_labs.appliances.radius_session.time.monotonic', side_effect=[0, 3]):
            with self.assertRaisesRegex(RuntimeFailure, 'did not complete'): group.__exit__(None, None, None)
        self.assertFalse(group.closed); group.path.rmdir.assert_not_called()
        kill.write_text.assert_called_once_with('1')

    def test_parent_requires_valid_managed_name_and_v1_never_creates_group(self):
        with self.assertRaises(ValueError): session_parent(Mock(), '../other-node')
        group = SessionGroup.__new__(SessionGroup); group.path = Mock()
        with patch('network_labs.appliances.radius_session.CGROUP_ROOT') as root:
            (root / 'cgroup.controllers').is_file.return_value = False
            with self.assertRaisesRegex(RuntimeFailure, 'cgroup v2'): group.__enter__()
        group.path.mkdir.assert_not_called()
