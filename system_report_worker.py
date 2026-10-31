"""Isolated desktop system-report process, with atomic final-file delivery."""
def export_system_report(project, destination, events, stop):
    import os
    import shutil
    import tempfile
    from pathlib import Path
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    import matplotlib
    matplotlib.use('Agg')
    from pcs_reports import export_workspace
    from calculation_scheduler import CalculationCancelled
    target = Path(destination)
    partial = target.with_name(target.name + '.partial')
    try:
        with tempfile.TemporaryDirectory(prefix='power-system-report-') as work:
            result = export_workspace(project, Path(work)/'系统报告包.zip', cancelled=stop.is_set,
                                      progress=lambda done, total, label: events.put(('progress', f'{done}/{total} · {label}')))
            if stop.is_set():
                raise CalculationCancelled()
            shutil.copyfile(result['path'], partial)
            os.replace(partial, target)
            result['path'] = str(target)
            events.put(('done', result))
    except CalculationCancelled:
        events.put(('cancelled', '报告已取消。'))
    except Exception as error:
        events.put(('error', str(error)))
    finally:
        if partial.is_file():
            partial.unlink()
