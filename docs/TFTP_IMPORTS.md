# Import local files into the TFTP example

`example --tftp --tftp-file NAME=PATH` embeds the selected file's exact bytes
as canonical Base64 in the generated manifest. Repeat the option for up to
eight files, each at most 65536 bytes. Empty files are supported.
Specifying imports replaces the built-in sample files.

```bash
python3 -m network_labs.appliances example --tftp \
  --rootfs /var/lib/network-labs/rootfs \
  --tftp-file image.bin=./image.bin \
  --tftp-file config.txt=./public-config.txt > tftp-lan.json
sudo python3 -m network_labs.appliances start tftp-lan.json
sudo python3 -m network_labs.appliances tftp-read \
  tftp-lan PC1 192.0.2.20 image.bin
```

The rootfs must include dnsmasq, as described in the
[native LAN guide](NATIVE_LAN_CORE.md). `NAME` is the remote filename: one
ASCII name containing letters, digits, underscore, dot or hyphen, at most
128 characters, excluding `.` and `..`. Duplicate names and directory
components are rejected. The first `=` separates name from local path;
paths can contain additional `=` characters.

Only regular files are imported. Reads stop after 65537 bytes to reject
oversized content without loading an unbounded file. FIFOs and directories
are rejected. A failed import produces no JSON manifest on stdout; when
using shell redirection, check the command's exit status before starting it.

The manifest contains the imported content, not its original filesystem path.
Changing or removing the source file afterwards does not change the lab;
regenerate the manifest and recreate the lab to update its files. Text files
are also imported as exact bytes, without newline or encoding conversion.

TFTP serves these files without authentication and does not support uploads.
Select public lab content, not credentials or private keys. Base64 is an
encoding, not encryption. Existing transfer size, retry and deadline limits
still apply; `--sha256` on `tftp-read` can check the expected payload digest.
