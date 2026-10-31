"""One owned process retains one solved design; no numerical work on HTTP loop."""
import gc
from pathlib import Path
import traceback


def worker_main(inbox, outbox, generation, operation_cancellations, folder):
    import signal
    # Windows delivers console Ctrl+C to children too. The parent owns the
    # shutdown handshake and must be allowed to drain/cancel this worker.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    import os
    os.environ['MPLBACKEND'] = 'Agg'
    from design_engine.service import calculate, export_report, SpecValidationError
    from calculation_scheduler import CalculationCancelled
    from web_app.presentation import present
    current, current_id, compensation = None, None, None
    current_name = ''
    root = Path(folder).resolve()
    while True:
        command = inbox.get()
        if command is None:
            return
        from design_theme import select
        select(command.get('presentation', 'default'))
        identity = command['id']
        token = command['generation']
        cancellation_slot = command.get('cancellation_slot')
        operation_token = command.get('operation_token')
        cancelled = lambda: (generation.value != token or
            (cancellation_slot is not None and operation_cancellations[cancellation_slot] == operation_token))
        try:
            if cancelled():
                raise CalculationCancelled()
            outbox.put(dict(id=identity, event='started'))
            if command['kind'] == 'workspace_export':
                from pcs_reports import export_workspace
                directory=root/identity;directory.mkdir(exist_ok=True)
                def workspace_progress(done,total,label):
                    outbox.put(dict(id=identity,event='progress',done=done,total=total,label=label))
                result=export_workspace(command['spec'],directory/'PCS辅源报告包.zip',cancelled=cancelled,progress=workspace_progress)
                # Any preceding interactive run has been superseded by this job.
                current,current_id,compensation=None,None,None
            elif command['kind'] == 'calculate':
                current_name=command['spec'].get('__web_project_title','')
                # Free the previous numerical snapshot before allocating another.
                current, current_id, compensation = None, None, None
                gc.collect()
                def progress(done, total, label):
                    outbox.put(dict(id=identity, event='progress', done=done, total=total, label=label))
                run = calculate(command['spec'], analysis='endpoints', include_loop=True,
                    include_efficiency=True, include_cross_regulation=command.get('cross_regulation', False),
                    cancelled=cancelled, progress=progress)
                try:
                    if cancelled():
                        raise CalculationCancelled()
                    result = present(run)
                    current, current_id = run, identity
                    compensation = command['spec'].get('__comp')
                    if not isinstance(compensation, dict):
                        compensation = None
                finally:
                    del run  # Also release cancelled/failed temporary snapshots.
            else:
                if current is None or current_id != command['job_id']:
                    raise ValueError('计算快照已被替换，请重新计算当前设计')
                from design_theme import report_name
                report_name(current_name)
                directory = root/current_id
                directory.mkdir(exist_ok=True)
                if command['kind'] == 'chart':
                    from web_app.charts import render
                    filename = f"{command['chart']}-{command['case']}-{command['output']}.png"
                    path = directory/filename
                    if not path.is_file():
                        render(current, path, command['case'], command['chart'], command['output'])
                    result = dict(path=str(path), media_type='image/png')
                elif command['kind'] == 'export':
                    suffix = command['format']
                    if suffix == 'comparison':
                        from spice_runtime import compare_design
                        def simulation_progress(done,total,label):
                            outbox.put(dict(id=identity,event='progress',done=done,total=total,label=label))
                        destination=directory/('仿真与设计计算对比报告-'+identity+'.zip')
                        comparison=compare_design(current,destination,cancelled=cancelled,progress=simulation_progress)
                        result=dict(path=str(destination),media_type='application/zip',
                            comparison={key:comparison[key] for key in ('successful','total','fra_successful','fra_total','cross_successful','cross_total','incomplete')})
                        if cancelled():raise CalculationCancelled()
                        outbox.put(dict(id=identity,event='done',result=result))
                        continue
                    real = bool(command.get('mos_real_time', False))
                    path = directory/('design-report-'+('real' if real else 'staged')+'.'+suffix)
                    # Immutable per-run files: concurrent downloads never see a
                    # report ZIP being overwritten. Failed authoring isn't cached.
                    if not path.is_file():
                        pending = directory/('pending-'+identity+'.'+suffix)
                        try:
                            if suffix == 'json':
                                current.save(pending)
                            elif suffix == 'zip':
                                from spice_export import export_project
                                prepared=current.runtime_bundle()
                                export_project(pending,prepared['base_spec'],bundle=prepared)
                            else:
                                export_report(current, pending, compensation_state=compensation, mos_real_time=real)
                            pending.replace(path)
                        finally:
                            pending.unlink(missing_ok=True)
                    media_types = dict(json='application/json', zip='application/zip',
                        xlsx='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        docx='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
                    result = dict(path=str(path),media_type=media_types[suffix])
                elif command['kind'] == 'action':
                    from web_app.actions import execute
                    path = directory/('action-'+identity+'.png')
                    def progress(done, total, label):
                        outbox.put(dict(id=identity, event='progress', done=done, total=total, label=label))
                    try:
                        result = execute(current, command['action'], command['options'], path,
                            cancelled=cancelled, progress=progress)
                        if cancelled():
                            raise CalculationCancelled()
                    except BaseException:
                        path.unlink(missing_ok=True)
                        raise
                else:
                    raise ValueError('未知计算操作')
            if cancelled():
                raise CalculationCancelled()
            outbox.put(dict(id=identity, event='done', result=result))
        except CalculationCancelled:
            outbox.put(dict(id=identity, event='cancelled'))
        except SpecValidationError as exc:
            outbox.put(dict(id=identity, event='error', error=dict(code='invalid_spec', message=str(exc), issues=exc.issues)))
        except Exception as exc:
            # Detailed traceback remains on this machine, not in an HTTP response.
            with (root/'worker.log').open('a', encoding='utf-8') as stream:
                traceback.print_exc(file=stream)
            outbox.put(dict(id=identity, event='error', error=dict(code='calculation_failed', message=str(exc))))
