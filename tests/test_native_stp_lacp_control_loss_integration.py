"""One-way LACP/Slow Protocol loss while every physical member retains carrier."""
import os
import unittest

from test_native_stp_lacp_carrier_integration import STPLACPPathScenario


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeSTPLACPControlLossTests(STPLACPPathScenario, unittest.TestCase):
    def test_one_way_control_loss_min_links_paths_and_saved_restart(self):
        self.exercise(control_loss=True)
