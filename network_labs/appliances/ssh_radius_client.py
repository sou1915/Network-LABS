"""BusyBox-only SSH credential and framed shell client; no NAS secret."""
CLIENT = r'''#!/bin/sh
PATH=/bin:/usr/bin
LC_ALL=C
export PATH LC_ALL
unset ENV BASH_ENV CDPATH username password IFS
umask 077
producer= transport= producer_start= transport_start= work= tty_mode=
process_start() {
    record=$(/bin/busybox cat "/proc/$1/stat" 2>/dev/null) || return 1
    record=${record##*) }
    set -- $record
    [ "$#" -ge 20 ] || return 1
    shift 19
    printf '%s' "$1"
}
cleanup() {
    trap - EXIT HUP INT TERM
    for role in producer transport; do
        case "$role" in
            producer) child=$producer; birth=$producer_start;;
            transport) child=$transport; birth=$transport_start;;
        esac
        if [ -n "$child" ]; then
            now=$(process_start "$child")
            if [ -n "$birth" ] && [ "$now" = "$birth" ]; then kill "$child" 2>/dev/null; fi
            wait "$child" 2>/dev/null
        fi
    done
    [ -z "$tty_mode" ] || /bin/busybox stty "$tty_mode" 2>/dev/null
    [ -z "$work" ] || /bin/busybox rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
action=$1
if /bin/busybox test -t 0; then
    tty_mode=$(/bin/busybox stty -g) || exit 125
    /bin/busybox stty -echo || exit 125
    printf 'RADIUS username: ' >&2
fi
IFS= read -r -n 65 username || exit 126
[ -z "$tty_mode" ] || printf '\nRADIUS password: ' >&2
IFS= read -r -n 129 password || exit 126
[ -z "$tty_mode" ] || printf '\n' >&2
[ "${#username}" -le 64 ] && [ "${#password}" -le 128 ] || exit 126
if [ "$action" = shell ] && [ -n "$tty_mode" ]; then
    action=shell-tty
    /bin/busybox stty raw -echo || exit 125
fi
work=$(/bin/busybox mktemp -d /tmp/ssh-radius.XXXXXX) || exit 125
/bin/busybox mkfifo "$work/input" "$work/output" || exit 125
exec 4<&0
{
    /bin/busybox cat <<REQUEST
NLSSH1
$action
$username
$password
REQUEST
    unset password
    case "$action" in shell|shell-tty) exec /bin/busybox cat;; esac
} <&4 > "$work/input" &
producer=$!; producer_start=$(process_start "$producer")
unset password
# -w is also an idle timeout in some BusyBox builds. The trusted dispatcher
# supplies a separate, policy-bounded overall timeout for this whole client.
/bin/busybox nc -w 3610 127.0.0.1 813 < "$work/input" > "$work/output" &
transport=$!; transport_start=$(process_start "$transport")
exec 3<"$work/output"
IFS= read -r -n 32 status <&3 || exit 126
case "$status" in
    OK)
        /bin/busybox cat <&3
        wait "$transport"; code=$?; transport=
        [ "$code" -eq 0 ] || exit 125
        exit 0;;
    SHELL)
        while IFS= read -r -n 4097 packet <&3; do
            [ "${#packet}" -le 4096 ] || exit 125
            case "$packet" in
                D*) printf '%s' "${packet#D}" | /bin/busybox base64 -d || exit 125;;
                E*) code=${packet#E}
                    case "$code" in ''|*[!0-9]*) exit 125;; esac
                    [ "${#code}" -le 3 ] && [ "$code" -le 255 ] || exit 125
                    exit "$code";;
                *) exit 125;;
            esac
        done
        exit 125;;
    *) printf 'SSH RADIUS request denied or unavailable.\n' >&2; exit 126;;
esac
'''
