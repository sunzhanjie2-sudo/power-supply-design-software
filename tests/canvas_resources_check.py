"""Owned Tk windows: raster lifecycle, redraw coalescing and numeric defaults."""
import io
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from matplotlib.figure import Figure
from resource_canvas import EfficientFigureCanvasTkAgg
from runtime_resources import configure_numeric_threads


class CanvasResourcesChecks(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.attributes('-alpha',0);self.root.geometry('640x480')
        self.errors=[]
        self.root.report_callback_exception=lambda *e:self.errors.append(e)
        self.nb=ttk.Notebook(self.root);self.nb.pack(fill='both',expand=True)
        self.page=ttk.Frame(self.nb);self.other=ttk.Frame(self.nb)
        self.nb.add(self.page,text='Chart');self.nb.add(self.other,text='Other')
        self.figure=Figure(figsize=(6,4),dpi=100)
        self.ax=self.figure.subplots();self.line,=self.ax.plot([0,1,2],[2,3,1])
        self.canvas=EfficientFigureCanvasTkAgg(self.figure,self.page)
        self.canvas.get_tk_widget().pack(fill='both',expand=True)

    def tearDown(self):
        self.canvas.dispose()
        for job in self.root.tk.splitlist(self.root.tk.call('after','info')):
            self.root.after_cancel(job)
        self.root.destroy()
        self.assertEqual(self.errors,[])

    def test_unvisited_canvas_has_tiny_photo_but_preserves_figure_size(self):
        self.assertEqual(self.canvas._tkphoto.width(),1)
        self.assertEqual(self.canvas._tkphoto.height(),1)
        self.assertEqual(tuple(self.figure.get_size_inches()),(6,4))
        self.canvas.request_draw()
        self.assertIsNone(self.canvas._idle_draw_id)
        self.assertFalse(hasattr(self.canvas,'renderer'))

    def test_many_draw_requests_coalesce_into_one(self):
        self.root.update()
        before=self.canvas._resource_draw_count
        for _ in range(80):self.canvas.request_draw()
        self.assertIsNotNone(self.canvas._idle_draw_id)
        self.root.update()
        self.assertEqual(self.canvas._resource_draw_count,before+1)

    def test_hidden_page_releases_rasters_and_remaps_same_dimensions(self):
        self.root.update()
        original=self.canvas.get_width_height()
        self.assertTrue(hasattr(self.canvas,'renderer'))
        self.nb.select(self.other);self.root.update()
        self.assertFalse(hasattr(self.canvas,'renderer'))
        self.assertIsNone(self.canvas._lastKey)
        self.assertEqual(self.canvas._tkphoto.width(),1)
        self.assertIsNone(self.canvas._idle_draw_id)
        for _ in range(4):
            self.nb.select(self.page);self.root.update()
            self.assertTrue(hasattr(self.canvas,'renderer'))
            self.assertEqual(self.canvas.get_width_height(),original)
            self.nb.select(self.other);self.root.update()
        self.assertEqual(list(self.line.get_ydata()),[2,3,1])

    def test_explicit_hidden_draw_and_png_export_are_not_suppressed(self):
        self.canvas.draw()
        self.assertEqual(self.canvas._tkphoto.width(),600)
        self.assertEqual(self.canvas.get_renderer().width,600)
        output=io.BytesIO();self.figure.savefig(output,format='png',dpi=140)
        self.assertTrue(output.getvalue().startswith(b'\x89PNG'))
        self.assertIs(self.figure.canvas,self.canvas)
        self.assertEqual(list(self.line.get_ydata()),[2,3,1])

    def test_hidden_sentinel_resize_does_not_destroy_dimensions(self):
        self.canvas.resize(type('Event',(),dict(width=1,height=1))())
        self.assertEqual(tuple(self.figure.get_size_inches()),(6,4))

    def test_reattaching_high_dpi_rail_does_not_multiply_dpi_or_text(self):
        from matplotlib.backend_bases import FigureCanvasBase
        self.root.tk.call('tk','scaling',2.)
        self.ax.set_title('OUT1 · 反馈/基准路',fontsize=12)
        heights=[]
        for _ in range(6):
            self.root.update();self.canvas.draw()
            self.assertEqual(self.figure.dpi,100)
            heights.append(self.ax.title.get_window_extent(self.canvas.get_renderer()).height)
            self.canvas.dispose();self.canvas.get_tk_widget().destroy()
            FigureCanvasBase(self.figure)
            self.canvas=EfficientFigureCanvasTkAgg(self.figure,self.page)
            self.canvas.get_tk_widget().pack(fill='both',expand=True)
        self.assertLess(max(heights),min(heights)*1.1)

    def test_dispose_cancels_idle_job_and_is_idempotent(self):
        self.root.update();self.canvas.request_draw()
        self.canvas.dispose();self.canvas.dispose();self.root.update()
        self.assertIsNone(self.canvas._idle_draw_id)
        self.assertFalse(hasattr(self.canvas,'renderer'))
        self.assertEqual(self.canvas._tkphoto.width(),1)


class NumericDefaultsChecks(unittest.TestCase):
    def test_single_thread_defaults_are_process_only(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(configure_numeric_threads(),1)
            self.assertEqual(os.environ['OPENBLAS_NUM_THREADS'],'1')
            self.assertEqual(os.environ['OMP_NUM_THREADS'],'1')

    def test_explicit_library_override_is_preserved(self):
        with patch.dict(os.environ,{'OPENBLAS_NUM_THREADS':'4','POWER_DESIGN_NUM_THREADS':'2'},clear=True):
            configure_numeric_threads()
            self.assertEqual(os.environ['OPENBLAS_NUM_THREADS'],'4')
            self.assertEqual(os.environ['MKL_NUM_THREADS'],'2')


if __name__=='__main__':unittest.main(verbosity=2)
