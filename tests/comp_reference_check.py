"""Check actual compensation reference rendering from source and bundle data."""
import argparse
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


def check(bundle=None):
    root = tk.Tk()
    root.withdraw()
    app = main.PowerSupplyAnalyzer(root)
    try:
        def verify_all(label):
            for key, title in app.COMP_TOPOS:
                app.comp_type.set(title)
                app._draw_comp_schematic()
                errors = '\n'.join(text.get_text() for text in app.ax_comp.texts)
                assert len(app.ax_comp.images) == 1, f'{label} {key}: {errors}'
                data = app.ax_comp.images[0].get_array()
                assert data.shape[0] > 100 and data.shape[1] > 100
            print(f'{label}: all 4 compensation reference images rendered.')

        verify_all('Source')
        if bundle is not None:
            bundle = Path(bundle).resolve()
            with patch.object(main.sys, 'frozen', True, create=True), \
                    patch.object(main.sys, '_MEIPASS', str(bundle), create=True):
                for filename in app.COMP_IMAGES.values():
                    path = main.resource_path(str(Path('comp_images') / filename))
                    assert Path(path) == bundle / 'comp_images' / filename
                verify_all('Bundle data')
    finally:
        app._closing = True
        for job in (app.update_timer, app._font_timer, app._initial_update_job, app._control_warmup_job):
            if job is not None:
                root.after_cancel(job)
        root.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle')
    check(parser.parse_args().bundle)
