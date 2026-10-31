"""Explicit native strict-LACP policy must be real and cannot silently degrade."""
import copy
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import stp_lacp_lab
from network_labs.appliances.lacp import configure, drift, preflight_strict, strict_value
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.spec import validate


class StrictLACPTests(unittest.TestCase):
    def test_policy_validation_and_legacy_omission(self):
        self.assertNotIn('lacp_strict', stp_lacp_lab('/rootfs')['nodes'][4]['port_channels']['bond1'])
        for value in (True, False):
            spec = stp_lacp_lab('/rootfs', lacp_strict=value)
            self.assertIs(spec['nodes'][4]['port_channels']['bond1']['lacp_strict'], value)
        for value in (1, 0, 'on', 'false', []):
            spec = stp_lacp_lab('/rootfs')
            spec['nodes'][4]['port_channels']['bond1']['lacp_strict'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'boolean'):
                validate(spec)

    def test_tool_preflight_is_read_only_and_omitted_policy_does_not_probe(self):
        with patch('network_labs.appliances.runtime.run') as run:
            preflight_strict(stp_lacp_lab('/rootfs')); run.assert_not_called()
            run.return_value = subprocess.CompletedProcess([], 255, '', 'lacp_rate RATE')
            with self.assertRaisesRegex(RuntimeFailure, 'requires iproute2'):
                preflight_strict(stp_lacp_lab('/rootfs', lacp_strict=True))
            run.assert_called_once_with(['ip', 'link', 'help', 'bond'], check=False)
            run.return_value = subprocess.CompletedProcess([], 255, '', 'lacp_strict LACP_STRICT')
            preflight_strict(stp_lacp_lab('/rootfs', lacp_strict=True))

    def test_kernel_rejection_or_ignored_attribute_never_enslaves_members(self):
        node = stp_lacp_lab('/rootfs', lacp_strict=True)['nodes'][4]
        for result, readback in ((1, True), (0, None), (0, False), (0, True)):
            calls = []
            def ns(index, *args, **options):
                calls.append(args)
                if args == ('ip', '-j', '-d', 'link', 'show'):
                    return subprocess.CompletedProcess(args, 0, json.dumps([{'ifname': p} for p in ('eth2', 'eth3')]), '')
                if args[:3] == ('ip', 'link', 'add'):
                    self.assertEqual(args[-2:], ('lacp_strict', 'on'))
                    return subprocess.CompletedProcess(args, result, '', 'unsupported')
                data = {} if readback is None else {'lacp_strict': readback}
                return subprocess.CompletedProcess(args, 0, json.dumps([{'ifname': 'bond1', 'linkinfo': {'info_data': data}}]), '')
            manager = SimpleNamespace(ns=ns)
            with self.subTest(result=result, readback=readback):
                if result or readback is not True:
                    with self.assertRaisesRegex(RuntimeFailure, 'lacp_strict'): configure(manager, 4, node, {})
                    self.assertFalse(any('master' in c for c in calls), calls)
                else:
                    self.assertEqual(configure(manager, 4, node, {}), {'bond1'})
                    self.assertTrue(any(c[-2:] == ('master', 'bond1') for c in calls))

    def test_drift_distinguishes_missing_false_and_true_and_edits_require_recreation(self):
        node = stp_lacp_lab('/rootfs', lacp_strict=True)['nodes'][4]
        for actual in ({}, {'lacp_strict': False}, {'lacp_strict': 'on'}):
            errors = drift(node, {'links': [{'ifname': 'bond1', 'linkinfo': {'info_data': actual}}]})
            self.assertEqual(any('lacp_strict' in e for e in errors), actual.get('lacp_strict') != 'on')
        previous = copy.deepcopy(node); node['port_channels']['bond1']['lacp_strict'] = False
        with self.assertRaisesRegex(ValueError, 'recreation'): adapters(node, previous)
        for value in (None, 'unknown', ''): self.assertIsNone(strict_value({'lacp_strict': value}))
        self.assertIs(strict_value({'lacp_strict': 'off'}), False)
