"""Integration checks; run with DISPLAY or xvfb-run. No real network traffic."""
import os
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

@unittest.skipUnless(os.environ.get('DISPLAY'),'GUI requires an X display')
class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from network_labs.__main__ import App
        self.root=tk.Tk()
        self.errors=[]
        self.root.report_callback_exception=lambda *e:self.errors.append(str(e))
        self.app=App(self.root)
        self.root.update()

    def tearDown(self):
        self.app.pause()
        self.root.destroy()
        self.assertEqual(self.errors,[])

    def test_console_controls_actual_port_state(self):
        app=self.app
        app.terminals['SW1'].send('enable\nconfigure terminal\ninterface gi0/1\nshutdown')
        self.root.update()
        self.assertTrue(app.lab.nodes['SW1'].ports['gi0/1'].shutdown)
        self.assertFalse(app.lab.ping('PC1','192.168.20.10')[0])
        app.terminals['SW1'].send('no shutdown\nend\nshow vlan brief')
        self.assertTrue(app.lab.ping('PC1','192.168.20.10')[0])
        self.assertIn('10',app.terminals['SW1'].text.get('1.0','end'))

    def test_playback_pause_step_and_delete_invalidation(self):
        app=self.app
        app.ping(); self.root.update(); app.pause()
        self.assertEqual(len(app.hops),8)
        self.assertIsNone(app.timer)
        app.step(); self.assertEqual(app.index,1)
        app.replay(); self.assertTrue(app.running)
        app.selected='PC2'; app.selected_link=None; app.delete()
        self.root.update()
        self.assertFalse(app.running)
        self.assertIsNone(app.timer)
        self.assertEqual(app.hops,[])
        self.assertNotIn('PC2',app.lab.nodes)

    def test_console_tabs_and_block_window(self):
        app=self.app
        app.open_cli('R1'); app.open_cli('PC1'); self.root.update()
        self.assertEqual(set(app.terminals),{'SW1','R1','PC1'})
        app.terminals['PC1'].send('ipconfig')
        self.assertIn('192.168.10.10',app.terminals['PC1'].text.get('1.0','end'))
        app.terminals['SW1'].open_block('enable\nshow vlan brief')
        self.root.update()
        import tkinter as tk
        dialogs=[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)]
        self.assertEqual(len(dialogs),1)
        dialogs[0].destroy()

    def test_dialogs_and_minimum_window_size(self):
        app=self.app
        app.edit_port('SW1','gi0/1'); self.root.update()
        import tkinter as tk
        for w in self.root.winfo_children():
            if isinstance(w,tk.Toplevel):
                w.destroy()
        with patch('network_labs.__main__.messagebox.showerror') as error:
            app.cable_dialog('SW1','R1')
            error.assert_called_once()

    def test_save_reload_and_labs(self):
        app=self.app
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'lab.json')
            app.path=path; self.assertTrue(app.save())
            with patch('network_labs.__main__.filedialog.askopenfilename',return_value=path):
                app.load()
            self.assertEqual(app.lab.nodes['PC1'].address,'192.168.10.10/24')
        app.replace_lab(app.channel_demo); self.root.update()
        self.assertEqual(len(app.lab.links),5)
        self.assertTrue(all(app.lab.channel_state(l)[0] for l in app.lab.links))
        self.root.geometry('1180x800'); self.root.update(); app.fit()
        self.assertGreater(app.canvas.winfo_width(),500)
        self.assertGreater(app.canvas.winfo_height(),200)

    def test_terminal_inline_edit_history_and_transcript_protection(self):
        terminal=self.app.terminals['SW1']
        text=terminal.text
        text.focus_force(); self.root.update()
        text.insert('end-1c','enable')
        terminal.enter()
        self.assertEqual(terminal.session.mode,'priv')
        self.assertTrue(text.get('1.0','end-1c').endswith('SW1# '))
        self.assertEqual(text.cget('background'),'#000000')
        terminal.recall(-1)
        self.assertEqual(terminal.pending(),'enable')
        terminal.replace_input('')
        text.mark_set('insert','input_start')
        before=text.get('1.0','end-1c')
        text.event_generate('<BackSpace>'); self.root.update()
        self.assertEqual(before,text.get('1.0','end-1c'))
        text.mark_set('insert','1.0')
        text.event_generate('<Delete>'); self.root.update()
        self.assertEqual(before,text.get('1.0','end-1c'))
        terminal.send('configure terminal\ninterface gi0/1\nshutdown')
        self.assertTrue(text.get('1.0','end-1c').endswith('SW1(config-if)# '))

    def test_security_lab_dhcp_from_inline_console(self):
        app=self.app
        app.replace_lab(app.security_demo); self.root.update()
        app.open_cli('PC1'); app.open_cli('PC2')
        app.terminals['PC1'].send('ip dhcp')
        app.terminals['PC2'].send('ip dhcp')
        self.root.update()
        self.assertTrue(app.lab.ping('PC1',app.lab.nodes['PC2'].address.split('/')[0])[0])
