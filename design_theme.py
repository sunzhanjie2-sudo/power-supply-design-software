"""Presentation-only context; never a parameter of an electrical calculation."""
from contextvars import ContextVar

_theme = ContextVar('power_design_presentation', default='default')
_report_name = ContextVar('power_design_report_name', default='')


def select(name):
    if name not in ('default', 'pcs'):
        raise ValueError('Unknown presentation theme')
    _theme.set(name)
    _report_name.set('')


def is_pcs():
    return _theme.get() == 'pcs'


def report_name(value=None):
    if value is not None: _report_name.set(str(value)[:150])
    return _report_name.get()


def style_figure(fig):
    if not is_pcs():
        return
    from matplotlib.text import Text
    from matplotlib.colors import to_hex
    colors = {'#2068a0': '#2376e5', '#245eab': '#2376e5', '#d18532': '#ee8a37',
              '#4c8a79': '#119777', '#8677b2': '#7b62df', '#33465b': '#152238',
              '#2676b9':'#2376e5','#2f83ac':'#20aebf','#1f77b4':'#2376e5',
              '#ff7f0e':'#ee8a37','#2ca02c':'#119777','#d62728':'#da4b63','#9467bd':'#7b62df'}
    fig.set_facecolor('#ffffff')
    for ax in fig.axes:
        ax.set_facecolor('#ffffff')
        for spine in ax.spines.values(): spine.set_edgecolor('#dfe6ee')
        for line in ax.get_xgridlines()+ax.get_ygridlines(): line.set_color('#dfe6ee')
        for line in ax.lines:
            try: color = to_hex(line.get_color())
            except (ValueError, TypeError): continue
            if color in colors: line.set_color(colors[color])
        for patch in ax.patches:
            for getter,setter in ((patch.get_facecolor,patch.set_facecolor),(patch.get_edgecolor,patch.set_edgecolor)):
                try: color=to_hex(getter())
                except (ValueError,TypeError): continue
                if color in colors: setter(colors[color])
    for text in fig.findobj(Text):
        text.set_fontfamily('Microsoft YaHei')
        try: color = to_hex(text.get_color())
        except (ValueError, TypeError): continue
        if color in colors: text.set_color(colors[color])
