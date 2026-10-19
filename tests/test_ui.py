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

    def test_catalogue_and_import_validation(self):
        import tkinter as tk
        from network_labs.text_ui import ImportDialog
        self.app.catalogue(); self.root.update()
        dialogs=[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)]
        self.assertEqual(len(dialogs),1)
        dialogs[0].destroy()
        dialog=ImportDialog(self.app); self.root.update()
        self.assertTrue(dialog.validate())
        self.root.update()
        self.assertIsNotNone(dialog.result)
        original=self.app.lab
        dialog.set_text('[devices]\nPC1 windows-11\n[config PC1]\nunknown command')
        self.assertFalse(dialog.validate())
        self.assertIs(self.app.lab,original)
        dialog.set_text('[devices]\nPC1 linux-ubuntu')
        self.assertTrue(dialog.validate())
        dialog.apply(); self.root.update()
        self.assertEqual(self.app.lab.nodes['PC1'].profile,'linux-ubuntu')

    def test_pc_inspector_dns_and_interface_controls(self):
        from tkinter import ttk
        self.app.selected='PC1'; self.app.inspect(); self.root.update()
        self.app.fields['DNS (séparés par espace)'].set('1.1.1.1 8.8.8.8')
        def invoke(text):
            next(w for w in self.app.inspector.winfo_children() if isinstance(w,ttk.Button) and w.cget('text')==text).invoke()
            self.root.update()
        invoke('Appliquer IPv4')
        self.assertEqual(self.app.lab.nodes['PC1'].dns,['1.1.1.1','8.8.8.8'])
        invoke('Désactiver eth0')
        self.assertFalse(self.app.lab.ping('PC1','192.168.20.10')[0])
        invoke('Activer eth0')
        self.assertTrue(self.app.lab.ping('PC1','192.168.20.10')[0])

    def test_enterprise_lan_roles_and_dns_editor(self):
        import tkinter as tk
        from network_labs.__main__ import App
        self.app.replace_lab(App.lan_demo)
        for name in ('SRV1','PRN1','NAS1','CAM1','TEL1','IOT1'):
            self.app.selected=name;self.app.inspect();self.app.draw();self.root.update()
        self.assertTrue(self.app.lab.ping('PC1','printer.lan')[0])
        self.app.dns_editor('SRV1');self.root.update()
        dialogs=[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)]
        self.assertEqual(len(dialogs),1)
        dialogs[0].destroy()

    def test_firewall_policy_editor_applies_actual_policy(self):
        from network_labs.__main__ import App
        self.app.replace_lab(App.firewall_demo)
        self.app.selected='FW1';self.app.inspect();self.root.update()
        self.assertTrue(self.app.lab.ping('PC1','192.168.10.20')[0])
        editor=self.app.firewall_editor('FW1');self.root.update()
        editor.number.set('5');editor.action.set('deny');editor.source.set('any');editor.target.set('any');editor.add()
        self.root.update()
        self.assertFalse(self.app.lab.ping('PC1','192.168.10.20')[0])
        self.assertIn('5',editor.table.get_children())
        editor.table.selection_set('5');editor.remove()
        self.assertTrue(self.app.lab.ping('PC1','192.168.10.20')[0])
        editor.window.geometry('640x400');self.root.update()
        editor.panel.canvas.yview_moveto(1);self.root.update()
        self.assertAlmostEqual(editor.panel.canvas.yview()[1],1,places=2)
        editor.window.destroy()

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

    def test_prompt_stays_visible_on_laptop_sizes_and_repeated_config(self):
        app=self.app; terminal=app.terminals['SW1']
        for width,height in ((1300,668),(1024,600),(900,500),(1280,700)):
            self.root.geometry(f'{width}x{height}')
            self.root.update(); app.apply_layout(); self.root.update()
            for _ in range(4):
                terminal.send('enable' if terminal.session.mode=='user' else 'show running-config')
                terminal.send('configure terminal\ninterface gi0/1\ndescription test\nend')
                self.root.update()
                info=terminal.text.dlineinfo('end-1c')
                self.assertIsNotNone(info,(width,height,'prompt hidden'))
                self.assertGreaterEqual(info[1],0)
                self.assertLessEqual(info[1]+info[3],terminal.text.winfo_height(),(width,height,info))
            root_bottom=self.root.winfo_rooty()+self.root.winfo_height()
            self.assertLessEqual(terminal.text.winfo_rooty()+terminal.text.winfo_height(),root_bottom)
        app.toggle_console_focus(); self.root.update()
        self.assertEqual(len(app.middle.panes()),1)
        self.assertIsNotNone(terminal.text.dlineinfo('end-1c'))
        app.toggle_console_focus(); self.root.update()
        self.assertEqual(len(app.middle.panes()),2)

    def test_focus_modes_and_simulation_tab(self):
        app=self.app
        app.toggle_topology_focus(); self.root.update()
        self.assertTrue(app.topology_focus)
        self.assertEqual(len(app.middle.panes()),1)
        app.open_cli('PC1'); self.root.update()
        self.assertFalse(app.topology_focus)
        self.assertEqual(len(app.middle.panes()),2)
        app.show_test_panel(); self.root.update()
        self.assertEqual(app.inspector_book.select(),str(app.test_panel))
        app.toggle_console_focus(); app.set_place('PC'); self.root.update()
        self.assertFalse(app.console_focus)

    def test_integrated_mst_vtp_labs(self):
        app=self.app
        app.replace_lab(app.mst_demo); self.root.update()
        self.assertEqual(app.lab.stp(10)['SW2']['root'],'SW1')
        self.assertEqual(app.lab.stp(20)['SW2']['root'],'SW3')
        app.replace_lab(app.vtp_demo); self.root.update()
        self.assertEqual(app.lab.nodes['SW2'].vlans['30'],'USERS')
