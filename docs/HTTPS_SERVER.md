# Persistent node-local HTTPS

Optional `https_server` runs a real NGINX master and one worker inside a
managed OCI host until the lab stops. It is separate from `https-demo`,
which remains temporary host-Python demonstration traffic. The new service
binds only the declared IPv4 eth0 address on TCP/443, enables TLS 1.2/1.3,
and exposes one fixed readiness response: GET/HEAD `/` is 200, other paths
are 404 and other methods are 405. It is a protocol lab endpoint, not a
vendor GUI, application login, upload server or reverse proxy.

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --nginx /usr/sbin/nginx --https-ca-file /path/to/ca.pem \
  --https-certificate-file /path/to/server.pem --https-private-key-file /path/to/server.key \
  --output /path/to/server-rootfs
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox --output /path/to/client-rootfs
python3 -m network_labs.appliances example --https --rootfs /path/to/server-rootfs \
  --https-client-rootfs /path/to/client-rootfs > https.json
sudo python3 -m network_labs.appliances start https.json
sudo python3 -m network_labs.appliances probe https-lan PC2 192.0.2.10 --protocol https \
  --ca-file /path/to/ca.pem --json
```

Use a trusted NGINX build with built-in HTTP SSL support, such as Ubuntu's
nginx-core. The builder checks `-V`, packages its ELF dependencies under a
distinct application pathname, and adds an `https` service account. The
master opens the identity and listener; the worker runs as UID/GID 65531.
One worker and 16 worker connections are configured, with short request/send
timeouts, small header/body limits, no access log, no plaintext listener and
no persisted TLS tickets/session cache. These settings are not a total RAM
measurement; the existing node cgroup budget remains in force. The reference
ensures at least a 32 MiB server allocation without asserting measured usage.

Supply a matching unencrypted PEM key with mode 0600 and public CA/leaf-chain
files, each nonempty and at most 64 KiB. No CA signing key is required or
copied. The builder writes the leaf key mode 0600 from creation in a private
identity directory at `/etc/network-labs/https`. Non-HTTPS OCI nodes mask that
directory if they share the server image. Startup gives the identity directory/files root ownership inside the node
overlay without modifying the supplied base image. The worker cannot open its root-owned
key file; the master loads it before the worker drops privileges. No host
web-server config or host trust store is imported.

Manifest policy contains `interface:"eth0"`, `ca_sha256` and
`certificate_sha256`, hashing exact public PEM file bytes. The example reads
these public assets to create pins, never the raw private key. Startup checks
the pins, matching key/certificate, permissions and executable assets; NGINX
then tests its actual config before launch. Config edits require recreation.
The initial profile is a standalone numbered UP single-interface OCI IPv4
host; management/Syslog/other managed server co-location and IPv6 are refused.

Clients must choose an explicit CA and verify the target IP/DNS identity.
For the example probe, provision IP SAN `192.0.2.10`; for DNS probing, provision
the matching DNS SAN and configure the existing guest resolver profile.
NGINX presents the supplied leaf/chain. Its local CA asset is an explicit
provisioning/trust reference, not a client-authentication directive or proof
that a client accepts the certificate. There is no mutual TLS in this increment.

Inspection verifies config files, pinned public assets, a runtime-only key
digest and root ownership/mode 0600; it does not claim daemon liveness, successful certificate
validation or a delivered response. Changed assets block save, including
while the already-running daemon still has an old identity loaded in memory.
Saving exports only policy/rootfs references. Cold restore requires the
conforming offline assets and starts fresh daemons, with no keys in startup
JSON and no TLS/process/session snapshot. Automatic renewal/revocation,
user content, HTTP authentication, live reload and broader service coexistence
remain separate work.

`https-server-interop` checks repeated certificate-verified probes, an actual
GET body over TLS, 404/405 behavior, wrong CA and wrong-IP certificate controls
with independently proven live servers, encrypted payload capture, non-root
worker identity, masking on other nodes, config/CA/key-mode drift refusal,
service outage/restart, saved cold restore and host cleanup. Native evidence
is pending.

References: [NGINX HTTPS](https://nginx.org/en/docs/http/configuring_https_servers.html),
[SSL module](https://nginx.org/en/docs/http/ngx_http_ssl_module.html)
and [command-line config validation](https://nginx.org/en/docs/switches.html).
