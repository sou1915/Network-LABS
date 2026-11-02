/* BusyBox telnetd login: discard login metadata, drop privilege, fixed diagnostics. */
#define NL_BRIDGE_PORT 814
#define NL_CREDENTIAL_SECONDS 15
#define NL_DENIAL_TEXT "Telnet RADIUS request denied or unavailable.\n"
#define main ssh_relay_main
#include "ssh_radius_relay.c"
#undef main
#include <grp.h>
#include <linux/capability.h>
#include <sys/prctl.h>
#include <sys/syscall.h>

static int unprivileged(void) {
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) return -1;
    if (geteuid() == 0) {
        /* Remove every bounding capability before changing UID, including
         * capabilities newer than the build headers (EINVAL means absent). */
        for (int cap = 0; cap < 64; cap++) {
            if (prctl(PR_CAPBSET_DROP, cap, 0, 0, 0) && errno != EINVAL) return -1;
        }
        if (setgroups(0, NULL) || setgid(65532) || setuid(65532)) return -1;
    }
    struct __user_cap_header_struct header = {_LINUX_CAPABILITY_VERSION_3, 0};
    struct __user_cap_data_struct data[2]; memset(data, 0, sizeof(data));
    if (syscall(SYS_capset, &header, data)) return -1;
    if (getuid() != 65532 || geteuid() != 65532 || getgid() != 65532 || getegid() != 65532 || getgroups(0, NULL) != 0) return -1;
    for (int cap = 0; cap < 64; cap++) {
        int present = prctl(PR_CAPBSET_READ, cap, 0, 0, 0);
        if (present > 0 || (present < 0 && errno != EINVAL)) return -1;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--version")) {
        puts("Network LABS Telnet RADIUS login 1"); return 0;
    }
    if (argc == 2 && !strcmp(argv[1], "--shell-version")) {
        puts("Network LABS Telnet RADIUS shell 1"); return 0;
    }
    /* No hostname, USER environment, -f option or argv can authenticate a user.
     * Always obtain a fresh action and credentials from the Telnet PTY. */
    if (unprivileged() || !isatty(STDIN_FILENO)) return 125;
    char action[33]; deadline = now() + 15;
    if (write_all(STDERR_FILENO, "RADIUS action (identity/hostname/security-context/shell): ",
                  sizeof("RADIUS action (identity/hostname/security-context/shell): ") - 1) || line(STDIN_FILENO, action, 32)) {
        fputs(NL_DENIAL_TEXT, stderr); return 126;
    }
    if (strcmp(action, "identity") && strcmp(action, "hostname") && strcmp(action, "security-context") && strcmp(action, "shell")) {
        fputs(NL_DENIAL_TEXT, stderr); return 126;
    }
    return run(action, !strcmp(action, "shell") ? 3615 : 15);
}
