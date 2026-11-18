"""A device's CLI inside the workbench, as in Packet Tracer: one console per device, typed straight after the prompt.

« Press RETURN to get started! », then the device's prompt. « ? » answers at once and gives the typed line back,
Tab completes the word, ↑/↓ (or Ctrl+P/Ctrl+N) recall earlier lines, Ctrl+Z ends configuration, and long output
stops at « --More-- » (space: a page, Return: a line, any other key: stop). Lines go to the lab's console server
(console_server.py, started with the lab); requests run in a thread and Tk is only touched here.
"""
import queue
import threading
import tkinter as tk
import uuid

from . import console_server

BACKGROUND, FOREGROUND, ERROR = '#ffffff', '#000000', '#b00020'  # black on white, as Packet Tracer's CLI tab
PAGE = 24


class ConsoleWindow:
    def __init__(self, parent, lab, node, font='DejaVu Sans Mono', request=None, on_close=None, status='', synchronous=False):
        self.lab, self.node = lab, node
        self.request = request or (lambda payload: console_server.request(lab, payload))
        self.session = uuid.uuid4().hex
        self.history, self.position = [], 0
        self.results = queue.Queue()
        self.busy = False
        self.started = False  # « Press RETURN to get started! » until the first Return
        self.prompt = ''
        self.paging = None  # lines still to show after « --More-- »
        self.on_close = on_close
        self.synchronous = synchronous  # the project's CLI answers at once, in Tk's thread (it may redraw the plan)
        self.window = tk.Toplevel(parent)
        self.window.title(f'{node}')
        self.window.geometry('820x540')
        self.window.minsize(480, 280)
        self.window.configure(bg=BACKGROUND)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        frame = tk.Frame(self.window, bg=BACKGROUND)
        frame.pack(fill='both', expand=True)
        tk.Label(frame, text='CLI' + (f'   ·   {status}' if status else ''), bg='#e9e9e9', fg='#222', font=('DejaVu Sans', 9, 'bold'),
                 anchor='w', padx=8).pack(fill='x')
        self.text = tk.Text(frame, bg=BACKGROUND, fg=FOREGROUND, insertbackground=FOREGROUND, font=(font, 10), relief='flat',
                            wrap='char', padx=6, pady=4, undo=False)
        scroll = tk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.text.pack(side='left', fill='both', expand=True)
        self.text.tag_configure('error', foreground=ERROR)
        self.entry = self.text  # where the keyboard goes (kept for callers that focus it)
        self.text.mark_set('input', 'end-1c')
        self.text.mark_gravity('input', 'left')
        for sequence, handler in (('<Return>', self.submit), ('<KP_Enter>', self.submit), ('<Tab>', self.complete),
                                  ('<question>', self.help), ('<Up>', lambda e: self.recall(-1)),
                                  ('<Down>', lambda e: self.recall(1)), ('<Control-p>', lambda e: self.recall(-1)),
                                  ('<Control-n>', lambda e: self.recall(1)), ('<Control-z>', self.control_z),
                                  ('<Control-a>', lambda e: self.home()), ('<Control-e>', lambda e: self.end()),
                                  ('<Home>', lambda e: self.home()), ('<BackSpace>', self.backspace), ('<Key>', self.key)):
            self.text.bind(sequence, handler)
        self.write('\n\n\nPress RETURN to get started!\n\n\n')
        self.window.after(50, self.poll)
        self.text.focus_set()

    # ---- the editable line ----

    def typed(self):
        return self.text.get('input', 'end-1c')

    def set_typed(self, value):
        self.text.delete('input', 'end')
        self.text.insert('end', value)
        self.text.mark_set('insert', 'end-1c')
        self.text.see('end')

    def key(self, event):
        if self.paging is not None:
            return self.page(event.keysym)
        if self.busy:
            return 'break'
        if event.char and event.char.isprintable() and self.text.compare('insert', '<', 'input'):
            self.text.mark_set('insert', 'end-1c')  # typing always goes to the line being edited
        if event.keysym in ('Delete',) and self.text.compare('insert', '<', 'input'):
            return 'break'
        return None

    def backspace(self, event=None):
        if self.busy or self.paging is not None or self.text.compare('insert', '<=', 'input'):
            return 'break'
        return None

    def home(self):
        self.text.mark_set('insert', 'input')
        return 'break'

    def end(self):
        self.text.mark_set('insert', 'end-1c')
        return 'break'

    def write(self, text, tag=None):
        self.text.insert('end', text, tag or ())
        self.text.mark_set('input', 'end-1c')
        self.text.mark_set('insert', 'end-1c')
        self.text.see('end')

    # ---- requests (thread) and replies (Tk) ----

    def send(self, payload, then):
        self.busy = True
        if self.synchronous:
            try:
                reply = self.request(payload)
            except (OSError, ValueError) as error:
                reply = {'ok': False, 'error': f'% {error}'}
            self.busy = False
            return then(reply)

        def work():
            try:
                reply = self.request(payload)
            except (OSError, ValueError) as error:
                reply = {'ok': False, 'error': f'% Consoles du lab injoignables ({error}). Démarrer le lab ou « État ».'}
            self.results.put((then, reply))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                then, reply = self.results.get_nowait()
                self.busy = False
                if self.window.winfo_exists():
                    then(reply)
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.window.after(50, self.poll)

    def opened(self, reply):
        if not reply['ok']:
            self.write(reply['error'] + '\n', 'error')
            self.started = False
            return
        self.prompt = reply['prompt'].rstrip() if reply['prompt'].endswith('# ') or reply['prompt'].endswith('> ') \
            else reply['prompt']
        self.write(self.prompt)

    def answered(self, reply, keep=''):
        if not reply['ok']:
            self.write(reply['error'] + '\n', 'error')
            return self.prompt_line(keep)
        if reply.get('closed'):
            self.started, self.prompt = False, ''
            return self.write(f'\n{self.node} con0 is now available\n\n\n\n\n\nPress RETURN to get started.\n\n\n')
        prompt = reply['prompt']
        self.prompt = prompt[:-1] if prompt.endswith(('# ', '> ')) else prompt
        lines = reply['reply'].split('\n') if reply.get('reply') else []
        self.show(lines, keep)

    def show(self, lines, keep=''):
        """Output, a page at a time, then the prompt (and the line kept after « ? »)."""
        if len(lines) > PAGE:
            for line in lines[:PAGE]:
                self.write(line + '\n', 'error' if line.startswith('%') else None)
            self.paging = (lines[PAGE:], keep)
            return self.write(' --More-- ')
        for line in lines:
            self.write(line + '\n', 'error' if line.startswith('%') else None)
        self.prompt_line(keep)

    def prompt_line(self, keep=''):
        """The prompt, then the editable line (holding KEEP, the line typed before « ? »)."""
        self.write(self.prompt)
        self.set_typed(keep)

    def page(self, key):
        """At « --More-- »: space shows a page, Return one line, any other key stops (as on IOS)."""
        rest, keep = self.paging
        self.paging = None
        self.text.delete('input-10c', 'input')  # the « --More-- » marker
        self.text.mark_set('input', 'end-1c')
        if key == 'space':
            self.show(rest, keep)
        elif key in ('Return', 'KP_Enter'):
            self.write(rest[0] + '\n', 'error' if rest[0].startswith('%') else None)
            if rest[1:]:
                self.paging = (rest[1:], keep)
                self.write(' --More-- ')
            else:
                self.prompt_line(keep)
        else:
            self.write('\n')
            self.prompt_line(keep)
        return 'break'

    # ---- keys ----

    def submit(self, event=None):
        if self.paging is not None:
            return self.page('Return')
        if self.busy:
            return 'break'
        if not self.started:
            self.started = True
            self.text.delete('1.0', 'end')
            self.send({'op': 'open', 'session': self.session, 'node': self.node}, self.opened)
            return 'break'
        text = self.typed()
        self.write('\n')
        if text.strip():
            self.history.append(text)
        self.position = len(self.history)
        self.send({'op': 'line', 'session': self.session, 'node': self.node, 'text': text}, self.answered)
        return 'break'

    def help(self, event=None):
        """« ? » as on IOS: printed after the line, the answer below, then the prompt and the same line again."""
        if self.busy or not self.started or self.paging is not None:
            return 'break'
        text = self.typed()
        self.write('?\n')
        self.send({'op': 'line', 'session': self.session, 'node': self.node, 'text': text + '?'},
                  lambda reply: self.answered(reply, keep=text))
        return 'break'

    def complete(self, event=None):
        if self.busy or not self.started or self.paging is not None:
            return 'break'
        text = self.typed()

        def done(reply):
            words = reply.get('words', []) if reply['ok'] else []
            if len(words) == 1:
                partial = '' if text.endswith(' ') else text.split(' ')[-1]
                self.set_typed(text[:len(text) - len(partial)] + words[0] + ' ')
            else:
                self.window.bell()  # IOS completes only a unique word
        self.send({'op': 'complete', 'session': self.session, 'node': self.node, 'text': text}, done)
        return 'break'

    def control_z(self, event=None):
        if self.busy or not self.started:
            return 'break'
        self.write('^Z\n')
        self.send({'op': 'line', 'session': self.session, 'node': self.node, 'text': 'end'}, self.answered)
        return 'break'

    def recall(self, step):
        if not self.history or not self.started or self.busy:
            return 'break'
        self.position = max(0, min(len(self.history), self.position + step))
        self.set_typed(self.history[self.position] if self.position < len(self.history) else '')
        return 'break'

    def close(self):
        try:
            self.request({'op': 'close', 'session': self.session, 'node': self.node})
        except (OSError, ValueError):
            pass
        self.window.destroy()
        if self.on_close:
            self.on_close(self.node)
