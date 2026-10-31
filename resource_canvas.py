"""TkAgg with small hidden buffers and one owner-cancelled idle redraw.

Figure artists and their numerical data remain intact. Only the disposable
Agg raster and Tk image shrink when the notebook page/window is hidden.
Explicit draw()/savefig() keep their normal diagnostic/export semantics.
"""
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class EfficientFigureCanvasTkAgg(FigureCanvasTkAgg):
    def __init__(self,figure=None,master=None):
        from matplotlib.figure import Figure
        figure=Figure() if figure is None else figure
        # This application uses native pixel geometry and explicit UI type
        # sizes. Retired canvases must not become a new high-DPI baseline.
        self._resource_base_dpi=getattr(figure,'_power_design_base_dpi',figure.dpi)
        figure._power_design_base_dpi=self._resource_base_dpi
        figure._set_dpi(self._resource_base_dpi,forward=False)
        original=tuple(figure.get_size_inches())
        width,height=(max(1,int(v*figure.dpi)) for v in original)
        self._resource_root=master.winfo_toplevel() if master is not None else None
        self._resource_disposed=False
        self._resource_active=True
        self._resource_dirty=True
        self._resource_drawing=False
        self._resource_draw_count=0
        # Native TkAgg normally allocates a full-resolution PhotoImage for
        # every unvisited page. Keep the requested widget size, not that RAM.
        figure.set_size_inches(1/figure.dpi,1/figure.dpi,forward=False)
        try:
            super().__init__(figure,master)
        finally:
            figure.set_size_inches(*original,forward=False)
        if self._resource_root is None:
            self._resource_root=self._tkcanvas.winfo_toplevel()
        self._tkcanvas.configure(width=width,height=height)
        self._tkcanvas.bind('<Map>',self._resource_mapped,add='+')
        self._tkcanvas.bind('<Unmap>',self._resource_unmapped,add='+')
        self._tkcanvas.bind('<Destroy>',self._resource_destroyed,add='+')

    def _update_device_pixel_ratio(self,event=None):
        # Tk's widget dimensions are already native pixels in our DPI-aware
        # window. Applying Tk scaling again both inflates text and, when a
        # rail canvas is recreated, compounds Figure._original_dpi each time.
        self.figure._original_dpi=self._resource_base_dpi
        self.figure._set_dpi(self._resource_base_dpi,forward=False)
        self._device_pixel_ratio=1

    def _can_render(self):
        try:
            return (not self._resource_disposed and self._resource_active and
                    self._tkcanvas.winfo_exists() and self._tkcanvas.winfo_viewable())
        except tk.TclError:
            return False

    def _cancel_idle_draw(self):
        job,self._idle_draw_id=getattr(self,'_idle_draw_id',None),None
        if job:
            try:
                self._resource_root.after_cancel(job)
            except tk.TclError:
                pass

    def draw_idle(self):
        self._resource_dirty=True
        if not self._can_render() or self._idle_draw_id:
            return
        def redraw():
            self._idle_draw_id=None
            if self._can_render() and self._resource_dirty:
                self.draw()
        self._idle_draw_id=self._resource_root.after_idle(redraw)

    def request_draw(self):
        """Coalesced GUI publication; explicit draw stays eager for batch tools."""
        self.draw_idle()

    def draw(self):
        if self._resource_disposed:
            return
        self._cancel_idle_draw()
        width,height=self.get_width_height(physical=True)
        try:
            if self._tkphoto.width()!=width or self._tkphoto.height()!=height:
                self._tkphoto.configure(width=width,height=height)
                self._tkcanvas.coords(self._tkcanvas_image_region,width/2,height/2)
        except tk.TclError:
            return
        self._resource_drawing=True
        try:
            super().draw()
            self._resource_dirty=False
            self._resource_draw_count+=1
        finally:
            self._resource_drawing=False

    def resize(self,event):
        if self._resource_disposed:
            return
        # Preserve useful figure dimensions on never-mapped notebooks. Tk's
        # sentinel width=1 is not a real viewport or an export figure size.
        if not self._can_render() or event.width<=1 or event.height<=1:
            self._resource_dirty=True
            return
        current=self.get_width_height(physical=True)
        if current==(event.width,event.height):
            self.draw_idle()
            return
        super().resize(event)

    def _resource_mapped(self,_event=None):
        if self._can_render():
            width,height=self._tkcanvas.winfo_width(),self._tkcanvas.winfo_height()
            if width>1 and height>1:
                self.resize(type('Viewport',(),dict(width=width,height=height))())
            self.draw_idle()

    def _resource_unmapped(self,_event=None):
        self.release_buffers()

    def release_buffers(self):
        """Release only render buffers; retain plots, axes and source values."""
        self._cancel_idle_draw()
        self._resource_dirty=True
        if self._resource_drawing:
            return
        if hasattr(self,'renderer'):
            del self.renderer
        self._lastKey=None
        try:
            self._tkphoto.configure(width=1,height=1)
        except tk.TclError:
            pass

    def set_render_active(self,active):
        self._resource_active=bool(active)
        if self._resource_active:
            self.request_draw()
        else:
            self.release_buffers()

    def dispose(self):
        if self._resource_disposed:
            return
        self.release_buffers()
        self._resource_disposed=True
        job=getattr(self,'_event_loop_id',None)
        if job:
            try:
                self._tkcanvas.after_cancel(job)
            except tk.TclError:
                pass
            self._event_loop_id=None

    def _resource_destroyed(self,event):
        if event.widget is self._tkcanvas:
            self.dispose()
