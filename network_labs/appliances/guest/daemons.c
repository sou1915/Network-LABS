/* Network LABS guest agent: the proven daemons the agent runs for a service (dnsmasq, chrony, keepalived) instead of
 * speaking the protocol itself: their configuration written from checked fields, their process started, watched and
 * stopped, their answers read. Part of agent.c, which includes it: the agent is one compilation unit. */
#ifndef DNSMASQ_PROGRAM
#define DNSMASQ_PROGRAM "/usr/sbin/dnsmasq"
#endif
#ifndef CHRONYD_PROGRAM
#define CHRONYD_PROGRAM "/usr/sbin/chronyd"
#endif
#ifndef CHRONYC_PROGRAM
#define CHRONYC_PROGRAM "/usr/bin/chronyc"
#endif
#ifndef KEEPALIVED_PROGRAM
#define KEEPALIVED_PROGRAM "/usr/sbin/keepalived"
#endif

static double wall_now(void) {
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}
static char *const daemon_environment[] = {"PATH=/bin:/sbin:/usr/bin:/usr/sbin", "LC_ALL=C", NULL};

/* TEXT into PATH through PATH.new and a rename, so that a reader sees the old file or the new one: 0, or -1. */
static int write_file(const char *path, const char *text, mode_t mode) {
    char temporary[320];
    snprintf(temporary, sizeof(temporary), "%.300s.new", path);
    int fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, mode);
    if (fd < 0) {
        return -1;
    }
    size_t size = strlen(text);
    ssize_t written = write(fd, text, size);
    close(fd);
    if (written != (ssize_t)size || rename(temporary, path)) {
        unlink(temporary);
        return -1;
    }
    return 0;
}

/* What a daemon's process starts with: standard input from /dev/null, its output and errors to OUTPUT (or /dev/null when
 * OUTPUT is -1), the signals this agent ignores or catches back to their defaults. */
static void daemon_child(int output) {
    int null = open("/dev/null", O_RDWR);
    if (null < 0 || dup2(null, 0) < 0 || dup2(output >= 0 ? output : null, 1) < 0 || dup2(output >= 0 ? output : null, 2) < 0) {
        _exit(126);
    }
    for (int number = 1; number < NSIG; number++) {
        signal(number, SIG_DFL);
    }
    sigset_t none;
    sigemptyset(&none);
    sigprocmask(SIG_SETMASK, &none, NULL);
}

/* PROGRAM with ARGV as a child of this process, in a session of its own (ENV: NULL for daemon_environment): its pid, or -1. */
static pid_t spawn_child(const char *program, char *const argv[], int output, char *const env[]) {
    pid_t pid = fork();
    if (pid != 0) {
        return pid;
    }
    setsid();
    daemon_child(output);
    execve(program, argv, env ? env : daemon_environment);
    _exit(127);
}

/* PROGRAM as a daemon of its own (a grandchild, reparented to init): it outlives this process, as keepalived must when one
 * --vrrp instance hands the groups over to the next. 0 once started, or -1. */
static int spawn_daemon(const char *program, char *const argv[], char *const env[]) {
    pid_t first = fork();
    if (first < 0) {
        return -1;
    }
    if (first == 0) {
        setsid();
        pid_t second = fork();
        if (second == 0) {
            daemon_child(-1);
            execve(program, argv, env ? env : daemon_environment);
            _exit(127);
        }
        _exit(second < 0 ? 1 : 0);
    }
    int status;
    while (waitpid(first, &status, 0) < 0) {
        if (errno != EINTR) {
            return -1;
        }
    }
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : -1;
}

static void pause_for(double seconds) {
    struct timespec pause = {(time_t)seconds, (long)((seconds - (double)(time_t)seconds) * 1e9)};
    nanosleep(&pause, NULL);
}

/* 1 while the child PID runs; 0 once it has ended (reaped here). */
static int child_running(pid_t pid) {
    if (pid <= 0) {
        return 0;
    }
    int status;
    pid_t done = waitpid(pid, &status, WNOHANG);
    return done == 0 || (done < 0 && errno == EINTR);
}

/* A child stopped: SIGTERM, up to SECONDS for it to end, then SIGKILL; reaped. */
static void stop_child(pid_t pid, double seconds) {
    if (pid <= 0) {
        return;
    }
    kill(pid, SIGTERM);
    double deadline = monotonic_now() + seconds;
    while (child_running(pid) && monotonic_now() < deadline) {
        pause_for(.05);
    }
    if (child_running(pid)) {
        kill(pid, SIGKILL);
        while (waitpid(pid, NULL, 0) < 0 && errno == EINTR) {
        }
    }
}

/* A daemon that is not this process's child (keepalived): SIGTERM, up to SECONDS for it to go, then SIGKILL. */
static void stop_daemon(pid_t pid, double seconds) {
    if (pid <= 0) {
        return;
    }
    kill(pid, SIGTERM);
    double deadline = monotonic_now() + seconds;
    while (process_alive(pid) && monotonic_now() < deadline) {
        pause_for(.05);
    }
    if (process_alive(pid)) {
        kill(pid, SIGKILL);
    }
}

/* PROGRAM ARGV run to its end (SECONDS at most, then killed), its standard output into OUT (ROOM bytes, NUL-terminated):
 * its exit status, or -1. */
static int run_capture(const char *program, char *const argv[], char *out, size_t room, double seconds) {
    int pipes[2];
    out[0] = 0;
    if (pipe2(pipes, O_CLOEXEC)) {
        return -1;
    }
    pid_t pid = fork();
    if (pid < 0) {
        close(pipes[0]);
        close(pipes[1]);
        return -1;
    }
    if (pid == 0) {
        daemon_child(pipes[1]);
        execve(program, argv, daemon_environment);
        _exit(127);
    }
    close(pipes[1]);
    size_t used = 0;
    double deadline = monotonic_now() + seconds;
    for (;;) {
        double left = deadline - monotonic_now();
        struct pollfd wait = {pipes[0], POLLIN, 0};
        if (left <= 0 || poll(&wait, 1, (int)(left * 1000) + 1) <= 0) {
            break;
        }
        ssize_t n = read(pipes[0], out + used, room - 1 - used);
        if (n <= 0) {
            break;
        }
        used += (size_t)n;
        if (used >= room - 1) {
            break;
        }
    }
    out[used] = 0;
    close(pipes[0]);
    int status = 0;
    pid_t done = waitpid(pid, &status, WNOHANG);
    if (done == 0) {  /* still running (past SECONDS, or its output closed early): ended here */
        kill(pid, SIGKILL);
    }
    while (done != pid) {
        done = waitpid(pid, &status, 0);
        if (done < 0 && errno != EINTR) {
            return -1;
        }
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}

/* Field INDEX (from 0) of a comma-separated LINE (one line of chronyc -c), into OUT: 1, or 0 when the line has fewer. */
static int csv_field(const char *line, int index, char *out, size_t room) {
    const char *at = line;
    for (int i = 0; i < index; i++) {
        const char *comma = strpbrk(at, ",\n");
        if (!comma || *comma == '\n') {
            return 0;
        }
        at = comma + 1;
    }
    size_t length = strcspn(at, ",\n");
    if (length >= room) {
        length = room - 1;
    }
    memcpy(out, at, length);
    out[length] = 0;
    return 1;
}

/* The line of TEXT whose first field is FIRST (chronyc -c), or NULL. */
static const char *csv_line(const char *text, const char *first) {
    size_t length = strlen(first);
    for (const char *line = text; line && *line; line = strchr(line, '\n') ? strchr(line, '\n') + 1 : NULL) {
        if (!strncmp(line, first, length) && (line[length] == ',' || line[length] == '\n')) {
            return line;
        }
    }
    return NULL;
}
