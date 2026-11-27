# Contributing to Network LABS

## Languages

- What students read is in **French**: the application, its messages, the README and the user guides in `docs/`.
- What developers read is in **English**: code, comments, docstrings, commit messages, this file, `docs/STATUS.md`.
- Vendor CLIs and pages keep the vendor's own words (IOS, FortiOS, Windows, GNOME…), whatever the language.

## Where things are

| Path | What |
|---|---|
| `network_labs/__main__.py` | the desktop app (`network-labs`): opens the workbench |
| `network_labs/appliances/` | labs: the workbench (`ui*.py`), project format (`spec.py`), micro-VM and container runtimes (`runtime.py`), guest startup and control, the vendor CLIs (`vendor_config.py` and one `vendor_*.py` per dialect, `ios_*.py`), the command line (`__main__.py`, `network-labs-lab`) |
| `network_labs/appliances/guest/` | the guest agent, in C, running as root in every micro-VM; `agent.c` includes one file per part and is built as one compilation unit (one `gcc` command; tests include `agent.c` to reach its static functions) |
| `network_labs/native_*.js`, `native_device_web.html` | the device pages served by the local portal (`web_portal.py`): the Network LABS view, the Simple design, and the copies of products' own pages |
| `network_labs/appliances/assets/` | fonts, icons, stylesheets and pictures; each one's source, licence and changes are in its `README.md` and in `THIRD_PARTY_NOTICES.md` |
| `tests/` | unit and integration tests; `tests/fuzz/` the agent's fuzzer |
| `tools/` | maintainers' scripts: guest kernel build, asset builders, CI helpers, `check_added_lines.py` |

## Running the tests

```bash
xvfb-run -a python3 -m unittest discover -s tests
```

Tests that need more than Python skip themselves; to run them:

| Tests | Need | How |
|---|---|---|
| desktop and workbench | an X display | `xvfb-run -a` (Ubuntu: `xvfb`, `python3-tk`) |
| device pages in a browser (`test_page_smoke`, `test_product_pages`) | Node and Playwright with Chromium | `npm install --global playwright` then `npx playwright install chromium`; run with `NODE_PATH="$(npm root --global)"` |
| guest agent fuzzing (`test_agent_fuzz`) | clang with its fuzzer runtime | Ubuntu: `clang libclang-rt-18-dev`; `NETWORK_LABS_FUZZ_SECONDS=600` for a longer run |
| real micro-VMs (`test_native_microvm*`) | root, KVM, Firecracker, a guest kernel | `sudo env NETWORK_LABS_MICROVM_TESTS=1 NETWORK_LABS_MICROVM_KERNEL=/path/vmlinux python3 -m unittest tests.test_native_microvm -v` |
| real containers (`test_native_integration_*`, one module per topic) | root, crun and the tools in the CI job | `sudo env NETWORK_LABS_NATIVE_TESTS=1 …` as in `.github/workflows/tests.yml` |
| WebAssembly prototype (`test_micro_*`) | Wasmtime | `pip install -r experiments/micro_appliances/requirements.txt` |

The CI (`.github/workflows/tests.yml`) runs all of these, the micro-VM ones on KVM when asked
(`workflow_dispatch`, suite `microvm-kvm`).

## Before a commit

```bash
python3 tools/check_added_lines.py origin/main
```

```bash
pyflakes network_labs tests tools
```

```bash
gcc -Wall -Wextra -Werror -o /tmp/agent network_labs/appliances/guest/agent.c
```

- `check_added_lines.py` checks the Python lines a change adds: one statement per line, 140 characters at most.
  Older code packs several statements per line; leave it, but write new code one statement per line.
- The device pages build HTML in JavaScript: pass every value that comes from the project through `esc()` (the
  configuration a student types, or a shared project file, can hold any text). `test_page_smoke` opens every model's
  page with hostile text in its configuration and fails if any of it runs.
- The guest agent runs as root. A protocol a proven daemon speaks goes to that daemon (keepalived, dnsmasq, chrony,
  BIRD, FRR), the agent writing its configuration from checked fields; what the agent still parses from the network
  (HSRP, port-guard frames, Syslog, TFTP), and any new field it reads, gets a handler in `tests/fuzz/agent_fuzz.c` and a
  well-formed seed in `tests/fuzz/seeds.py`.
- No vendor logo or proprietary picture in the pages (the one exception, the Windows logo on the Start button, is
  listed in `THIRD_PARTY_NOTICES.md`). A file taken from another project keeps its licence file and gets a note in
  `network_labs/appliances/assets/README.md` and a row in `THIRD_PARTY_NOTICES.md`.
- A feature lands with its tests (a real-KVM test for micro-VM features, see `docs/RELEASE_1.md`) and a line in
  `docs/STATUS.md`.

## Branches

`main` is the only long-lived branch. Work on a short branch and open a pull request to `main` early; keep it small
enough to review in one sitting.

## Licence

Network LABS is licensed under the GNU GPL, version 3 or any later version (`LICENSE`). By contributing you agree
that your contribution is licensed the same way.
