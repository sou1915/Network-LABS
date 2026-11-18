"""A device's CLI inside the workbench, as in Packet Tracer: one window per device, no terminal emulator, no password.

Lines go to the lab's console server (console_server.py, started with the lab) and come back with the device's
reply and prompt. ↑/↓ recall earlier lines, Tab completes a word (or lists the choices), « ? » shows the commands
that fit what is typed, without sending the line, as on IOS. Requests run in a thread: Tk is only touched here.
"""
import queue
import threading
import tkinter as tk
import uuid

from . import console_server

BACKGROUND, FOREGROUND, ACCENT, ERROR = '#0b1220', '#d7e3f4', '#7cc4ff', '#ff9b9b'


class ConsoleWindow:
    def __init__(self, parent, lab, node, font='DejaVu Sans Mono', request=None, on_close=None):
        self.lab, self.node = lab, node
        self.request = request or (lambda payload: console_server.request(lab, payload))
        self.session = uuid.uuid4().hex
        self.history, self.position = [], 0
        self.results = queue.Queue()
        self.busy = False
        self.on_close = on_close
        self.window = tk.Toplevel(parent)
        self.window.title(f'{node} — CLI')
        self.window.geometry('860x520')
        self.window.minsize(520, 300)
        self.window.configure(bg=BACKGROUND)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        mono = ('DejaVu Sans Mono', 10)
        frame = tk.Frame(self.window, bg=BACKGROUND)
        frame.pack(fill='both', expand=True, padx=6, pady=(6, 0))
        self.text = tk.Text(frame, bg=BACKGROUND, fg=FOREGROUND, insertbackground=FOREGROUND, font=mono, relief='flat',
                            wrap='char', padx=8, pady=6, state='disabled', takefocus=0)
        scroll = tk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.text.tag_configure('typed', foreground=ACCENT)
        self.text.tag_configure('error', foreground=ERROR)
        line = tk.Frame(self.window, bg=BACKGROUND)
        line.pack(fill='x', padx=6, pady=6)
        self.prompt = tk.StringVar(value='… ')
        tk.Label(line, textvariable=self.prompt, bg=BACKGROUND, fg=ACCENT, font=mono).pack(side='left')
        self.entry = tk.Entry(line, bg=BACKGROUND, fg=FOREGROUND, insertbackground=FOREGROUND, font=mono, relief='flat',
                              highlightthickness=0)
        self.entry.pack(side='left', fill='x', expand=True)
        self.entry.bind('<Return>', lambda event: self.submit())
        self.entry.bind('<Up>', lambda event: self.recall(-1))
        self.entry.bind('<Down>', lambda event: self.recall(1))
        self.entry.bind('<Tab>', lambda event: self.complete())
        self.entry.bind('<question>', lambda event: self.help())
        self.text.bind('<Button-1>', lambda event: self.entry.focus_set())
        self.send({'op': 'open', 'session': self.session, 'node': node}, self.opened)
        self.window.after(50, self.poll)
        self.entry.focus_set()

    # ---- requests (thread) and replies (Tk) ----

    def send(self, payload, then):
        self.busy = True
        self.entry.configure(state='disabled')

        def work():
            try:
                reply = self.request(payload)
            except (OSError, ValueError) as error:
                reply = {'ok': False, 'error': f'Consoles du lab injoignables ({error}). Démarrer le lab ou « État ».'}
            self.results.put((then, reply))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                then, reply = self.results.get_nowait()
                self.busy = False
                if self.window.winfo_exists():
                    self.entry.configure(state='normal')
                    self.entry.focus_set()
                    then(reply)
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.window.after(50, self.poll)

    def opened(self, reply):
        if not reply['ok']:
            return self.write(reply['error'] + '\n', 'error')
        self.write(reply['banner'] + '\n')
        self.prompt.set(reply['prompt'])

    def answered(self, reply):
        if not reply['ok']:
            return self.write(reply['error'] + '\n', 'error')
        if reply.get('reply'):
            self.write(reply['reply'] + '\n', 'error' if reply['reply'].startswith('%') else None)
        if reply.get('closed'):
            self.write('Terminal fermé. « Entrée » pour le rouvrir.\n')
            self.prompt.set('')
            return
        self.prompt.set(reply['prompt'])

    # ---- typing ----

    def submit(self):
        if self.busy:
            return 'break'
        text = self.entry.get()
        self.entry.delete(0, 'end')
        if not self.prompt.get():
            self.send({'op': 'open', 'session': self.session, 'node': self.node}, self.opened)
            return 'break'
        self.write(self.prompt.get(), None)
        self.write(text + '\n', 'typed')
        if text.strip():
            self.history.append(text)
        self.position = len(self.history)
        self.send({'op': 'line', 'session': self.session, 'node': self.node, 'text': text}, self.answered)
        return 'break'

    def help(self):
        """« ? » as on IOS: the matching commands are listed, the typed line stays."""
        if self.busy:
            return 'break'
        typed = self.entry.get()
        self.write(self.prompt.get(), None)
        self.write(typed + '?\n', 'typed')
        self.send({'op': 'line', 'session': self.session, 'node': self.node, 'text': (typed + ' ?') if typed.strip() else '?'},
                  self.answered)
        return 'break'

    def complete(self):
        if self.busy:
            return 'break'
        typed = self.entry.get()

        def done(reply):
            words = reply.get('words', []) if reply['ok'] else []
            if len(words) == 1:
                partial = '' if typed.endswith(' ') else typed.split(' ')[-1]
                head = typed[:len(typed) - len(partial)]
                self.entry.delete(0, 'end')
                self.entry.insert(0, head + words[0] + ' ')
            elif words:
                self.write(self.prompt.get() + typed + '\n', 'typed')
                self.write('  '.join(words) + '\n')
        self.send({'op': 'complete', 'session': self.session, 'node': self.node, 'text': typed}, done)
        return 'break'

    def recall(self, step):
        if not self.history:
            return 'break'
        self.position = max(0, min(len(self.history), self.position + step))
        self.entry.delete(0, 'end')
        if self.position < len(self.history):
            self.entry.insert(0, self.history[self.position])
        return 'break'

    def write(self, text, tag=None):
        self.text.configure(state='normal')
        self.text.insert('end', text, tag or ())
        self.text.configure(state='disabled')
        self.text.see('end')

    def close(self):
        try:
            self.request({'op': 'close', 'session': self.session, 'node': self.node})
        except (OSError, ValueError):
            pass
        self.window.destroy()
        if self.on_close:
            self.on_close(self.node)
