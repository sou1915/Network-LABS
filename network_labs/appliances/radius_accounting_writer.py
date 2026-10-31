"""Fixed accounting writer; untrusted attributes are data, never commands."""
SCRIPT = '/lab/radius/accounting-write.sh'
FLOCK = '/usr/lib/network-labs/freeradius/flock'
WRITER = r'''#!/bin/busybox sh
# rlm_exec exports request attributes. Persist only this bounded whitelist.
LC_ALL=C
export LC_ALL
umask 077
log=$1
user=${USER_NAME-}
sid=${ACCT_SESSION_ID-}
nas=${NAS_IP_ADDRESS-}
# shell_escape=yes normalizes names and quotes string attribute values.
user=${user#\"}; user=${user%\"}
sid=${sid#\"}; sid=${sid%\"}
case "$user" in ''|*[!A-Za-z0-9_.@-]*) exit 2;; esac
case "$sid" in ''|*[!A-Za-z0-9_.-]*) exit 2;; esac
case "$nas" in ''|*[!0-9.]*) exit 2;; esac
[ "${#user}" -le 64 ] && [ "${#sid}" -le 64 ] && [ "${#nas}" -le 15 ] || exit 2
case "${ACCT_STATUS_TYPE-}" in
    Start|1) status=Start; seconds=0; cause=0;;
    Stop|2)
        status=Stop
        seconds=${ACCT_SESSION_TIME-}
        case "$seconds" in ''|*[!0-9]*) exit 2;; esac
        [ "${#seconds}" -le 10 ] && [ "$seconds" -le 4294967295 ] || exit 2
        case "${ACCT_TERMINATE_CAUSE-}" in
            User-Request|1) cause=1;;
            Session-Timeout|5) cause=5;;
            Admin-Reset|6) cause=6;;
            NAS-Error|9) cause=9;;
            *) exit 2;;
        esac;;
    *) exit 2;;
esac
record="$status|$sid|$user|$nas|$seconds|$cause"
[ ! -L "$log" ] || exit 2
exec 9>>"$log" || exit 2
/usr/lib/network-labs/freeradius/flock -x 9 || exit 2
oldsize=$(/bin/busybox stat -c %s "$log") || exit 2
# External printf propagates short writes/flush errors; verify the whole line.
if /bin/busybox printf '%s\n' "$record" >&9 &&
    last=$(/bin/busybox tail -n 1 "$log") &&
    [ "$last" = "$record" ]; then
    exit 0
fi
# Remove any incomplete append while still holding the exclusive lock.
/bin/busybox truncate -s "$oldsize" "$log"
exit 2
'''
