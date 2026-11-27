"""The workbench's project files: new, the campus example, open, save, the preview of a plan. A mixin of ui.ApplianceWindow."""
import json
from pathlib import Path
from tkinter import filedialog, simpledialog
from .runtime import plan
from .spec import validate
from .campus import campus_example
from .ui_quick import blank_project
from .ui_bridge import private_json, public_topology


class ProjectFiles:
    def load_spec(self,spec,path=None):
        spec=validate(spec)
        self.path=Path(path) if path else None
        # Output and observations of the previous lab do not describe this one.
        self.vendor_observation=None
        self.write_output('',{},'Diagnostic réseau · lecture seule')
        self.editor.delete('1.0','end')
        self.editor.insert('1.0',json.dumps(spec,indent=2))
        self.config_key=None
        self.positions={name:tuple(point) for name,point in (spec.get('layout') or {}).items()}  # as last saved
        self.zoom=1.
        self.view_moved=False
        self.draw(public_topology(spec))
        self.fit_view()
        self.observation.set('Topologie déclarée · état runtime à actualiser.')

    def new_campus(self,security=False):
        if self.pending:
            return False
        rootfs=filedialog.askdirectory(parent=self.window,title='Rootfs Linux du laboratoire')
        if not rootfs:
            return False
        name=simpledialog.askstring('LAN sécurité access' if security else 'Campus entreprise','Nom du projet :',
                                    initialvalue='Access-security' if security else 'Campus-entreprise',parent=self.window)
        if not name:
            return False
        from .access_security import access_security_example
        try:
            self.load_spec((access_security_example if security else campus_example)(rootfs,name))
            self.tabs.select(self.topology_tab)
            return True
        except (ValueError,TypeError,KeyError) as error:
            self.error(error)
            return False

    def new(self):
        """A new, empty project (no question asked): devices come from the library."""
        if self.pending:
            return False
        used={p.stem for p in self.project_file(blank_project()).parent.glob('*.json')}
        name=next(n for n in ['mon-lab']+[f'mon-lab-{i}' for i in range(2,1000)] if n not in used)
        self.load_spec(blank_project(name))
        self.tabs.select(self.topology_tab)
        self.note.set('Nouveau projet vide : cliquer ou glisser un équipement depuis la bibliothèque.')
        return True

    def preview(self):
        if self.pending:
            return False
        try:
            spec=self.manifest()
            report=plan(spec)
        except (ValueError,TypeError,KeyError) as error:
            self.error(error)
            return False
        self.draw(public_topology(spec))
        self.observation.set('Topologie déclarée · état runtime à actualiser.')
        self.show_output(report)
        self.dock.select(self.output_tab)
        return True

    def open(self):
        if self.pending:
            return False
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('Native lab JSON','*.json')])
        if path:
            try:
                self.load_spec(json.loads(Path(path).read_text()),path)
                self.tabs.select(self.topology_tab)
            except (OSError,ValueError,TypeError,KeyError) as error:self.error(error)

    def save(self,ask=False):
        """Save the project: in its file, or (never saved) in the projects folder by its name, without a dialog."""
        if self.pending:
            return False
        try:
            spec=self.manifest()
            if ask:
                path=filedialog.asksaveasfilename(parent=self.window,defaultextension='.json',filetypes=[('Native lab JSON','*.json')])
            else:
                path=self.path or self.project_file(spec)
            if not path:
                return False
            self.path=Path(path).resolve()
            drawn=getattr(self,'drawn_positions',{})  # the workbench drawing comes back as it was left
            spec['layout']={name:[round(x,1),round(y,1)] for name,(x,y) in drawn.items() if name in {n['name'] for n in spec['nodes']}}
            private_json(self.path,spec)
            self.project_title.set(spec['name']+' · '+self.path.name)
            return True
        except (OSError,ValueError,TypeError,KeyError) as error:
            self.error(error)
            return False

    def busy(self,enabled):
        for button in self.buttons:
            button.state(['disabled'] if enabled else ['!disabled'])
        self.editor.configure(state='disabled' if enabled else 'normal')
        self.select_node()
