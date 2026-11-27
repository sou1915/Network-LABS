"""The guest agent under libFuzzer (tests/fuzz/agent_fuzz.c): every handler of what peers send (HSRP, VRRP, frames on a
security port, DNS, Syslog, TFTP) and of the fields the host types, with AddressSanitizer and UndefinedBehaviorSanitizer,
starting from one well-formed message each (tests/fuzz/seeds.py). Runs NETWORK_LABS_FUZZ_SECONDS (20 by default) when
clang and its fuzzer runtime are installed (Ubuntu: clang, libclang-rt-18-dev), in a network namespace of its own."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'fuzz'))
import seeds  # noqa: E402


def clang_fuzzer(folder):
    """clang when it links a fuzzer with the sanitizers here, else None."""
    clang = shutil.which('clang')
    if not clang:
        return None
    probe = Path(folder) / 'probe.c'
    probe.write_text('#include <stdint.h>\n#include <stddef.h>\nint LLVMFuzzerTestOneInput(const uint8_t *d, size_t n) { return 0; }\n')
    built = subprocess.run([clang, '-fsanitize=fuzzer,address,undefined', '-o', str(Path(folder) / 'probe'), str(probe)],
                           capture_output=True, timeout=120)
    return clang if built.returncode == 0 else None


def isolated():
    """The command prefix that gives the fuzzer an empty network namespace, when one can be had."""
    for prefix in (['unshare', '-n'], ['unshare', '-rn']):
        try:
            if subprocess.run(prefix + ['true'], capture_output=True, timeout=10).returncode == 0:
                return prefix
        except (OSError, subprocess.TimeoutExpired):
            pass
    return []


class SeedTest(unittest.TestCase):
    def test_every_handler_has_a_well_formed_seed(self):
        found = seeds.seeds()
        self.assertEqual({value[0] for value in found.values()}, set(range(11)))  # handlers 0..10 (11 is 10's twin)
        self.assertEqual(seeds.checksum(seeds.vrrp()[34:]), 0)  # the VRRP advert's own checksum holds


class AgentFuzzTest(unittest.TestCase):
    def test_the_agent_survives_its_fuzzer(self):
        with tempfile.TemporaryDirectory() as folder:
            clang = clang_fuzzer(folder)
            if not clang:
                self.skipTest('clang with the libFuzzer and sanitizer runtimes absent')
            work = Path(folder)
            for name in ('hsrp', 'vrrp', 'guard'):
                (work / 'run' / name).mkdir(parents=True)
            binary = work / 'agent_fuzz'
            defines = [f'-DHSRP_RUN="{work}/run/hsrp"', f'-DVRRP_RUN="{work}/run/vrrp"', f'-DGUARD_RUN="{work}/run/guard"',
                       f'-DSERVICES_RUN="{work}/run"']
            built = subprocess.run([clang, '-g', '-O1', '-fsanitize=fuzzer,address,undefined', '-fno-sanitize-recover=undefined',
                                    '-Wno-unused-function', *defines, '-o', str(binary), str(HERE / 'fuzz' / 'agent_fuzz.c')],
                                   capture_output=True, text=True, timeout=300)
            self.assertEqual(built.returncode, 0, built.stderr[-3000:])
            corpus = work / 'corpus'
            corpus.mkdir()
            for name, data in seeds.seeds().items():
                (corpus / name).write_bytes(data)
            seconds = int(os.environ.get('NETWORK_LABS_FUZZ_SECONDS', '20'))
            run = subprocess.run([*isolated(), str(binary), f'-max_total_time={seconds}', '-max_len=1700', '-timeout=10',
                                  f'-artifact_prefix={work}/', str(corpus)], capture_output=True, text=True, timeout=seconds + 300)
            report = run.stderr[-6000:]
            self.assertEqual(run.returncode, 0, report)
            self.assertIn('Done', report)


if __name__ == '__main__':
    unittest.main()
