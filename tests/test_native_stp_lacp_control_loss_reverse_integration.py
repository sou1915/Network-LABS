"""Active-to-passive control loss; both member carriers retained."""
import os
import unittest
from test_native_stp_lacp_carrier_integration import STPLACPPathScenario


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeSTPLACPReverseControlLossTests(STPLACPPathScenario, unittest.TestCase):
    def test_active_to_passive_min_links_two_failover_and_saved_restart(self):
        self.exercise(control_loss=True, receiver=5, thresholds=(2,))
