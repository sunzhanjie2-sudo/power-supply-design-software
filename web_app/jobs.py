"""Bounded job/operation bookkeeping with cooperative process cancellation."""
from collections import OrderedDict
from concurrent.futures import Future
import copy
import multiprocessing as mp
from pathlib import Path
import queue
import secrets
import shutil
import tempfile
import threading
import time

from .worker import worker_main


class JobManager:
    def __init__(self, presentation='default'):
        self.presentation = presentation
        self._context = mp.get_context('spawn')
        self._generation = self._context.Value('i', 0)
        self._operation_cancellations = self._context.Array('q', 64)
        self._operation_sequence = 0
        self._inbox = self._context.Queue(maxsize=32)
        self._outbox = self._context.Queue()
        self._temporary = tempfile.TemporaryDirectory(prefix='power-design-web-')
        self.root = Path(self._temporary.name).resolve()
        self._lock = threading.RLock()
        self._jobs, self._operations = OrderedDict(), OrderedDict()
        self._futures = {}
        self._closed = False
        self._process = None
        self._reader = None
        self.current_id = None

    def start(self):
        with self._lock:
            if self._process is not None and self._process.is_alive():
                return
            if self._process is not None:
                self._process.join(timeout=0)
            self._process = self._context.Process(target=worker_main,
                args=(self._inbox, self._outbox, self._generation, self._operation_cancellations, str(self.root)), daemon=True)
            self._process.start()
            if self._reader is None:
                self._reader = threading.Thread(target=self._receive, daemon=True, name='power-web-results')
                self._reader.start()

    def submit(self, spec, cross_regulation=False, *, workspace=False):
        with self._lock:
            if self._closed:
                raise ValueError('服务正在关闭')
            self.start()
            with self._generation.get_lock():
                self._generation.value += 1
                token = self._generation.value
            for record in self._jobs.values():
                if record['state'] in ('queued', 'running'):
                    record.update(state='cancelled', message='已由较新的计算请求替换')
            identity = secrets.token_hex(12)
            self.current_id = identity
            record = dict(id=identity, state='queued', generation=token, progress=0,
                message='等待独立计算进程', created_at=time.time(), result=None, error=None)
            self._jobs[identity] = record
            try:
                self._enqueue(dict(id=identity,kind='workspace_export' if workspace else 'calculate',generation=token,
                                   spec=copy.deepcopy(spec),cross_regulation=cross_regulation))
            except ValueError:
                self._jobs.pop(identity, None)
                self.current_id = None
                raise
            finally:
                while len(self._jobs) > 4:
                    old_id, _ = self._jobs.popitem(last=False)
                    self._remove_owned(old_id)
            return self.status(identity)

    def _enqueue(self, command):
        command['presentation'] = self.presentation
        future = Future()
        self._futures[command['id']] = future
        try:
            self._inbox.put_nowait(command)
        except queue.Full:
            del self._futures[command['id']]
            raise ValueError('任务队列已满，请等待或取消当前计算')
        return future

    def operate(self, job_id, kind, **options):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError('计算记录已过期')
            if job_id != self.current_id or job['state'] != 'succeeded':
                raise ValueError('仅能读取当前成功计算的快照')
            identity = secrets.token_hex(12)
            used_slots = {record.get('_cancellation_slot') for key, record in self._operations.items() if key in self._futures}
            slot = next((i for i in range(64) if i not in used_slots), None)
            if slot is None:
                raise ValueError('后台操作过多，请等待或取消操作')
            self._operation_sequence += 1
            sequence = self._operation_sequence
            self._operation_cancellations[slot] = 0
            record = dict(id=identity,job_id=job_id,kind=kind,state='queued',result=None,error=None,
                _cancellation_slot=slot, _operation_token=sequence)
            self._operations[identity] = record
            try:
                future = self._enqueue(dict(id=identity,job_id=job_id,kind=kind,
                    generation=job['generation'],cancellation_slot=slot,operation_token=sequence,**options))
            except ValueError:
                self._operations.pop(identity, None)
                raise
            while len(self._operations) > 64:
                key = next((key for key,value in self._operations.items()
                            if value['state'] not in ('queued','running') and key not in self._futures), None)
                if key is None:
                    break
                self._remove_operation(key)
            return identity, future

    def status(self, identity):
        with self._lock:
            record = self._jobs.get(identity)
            if record is None:
                raise KeyError('计算记录已过期')
            return copy.deepcopy({key:value for key,value in record.items() if key != 'result'})

    def result(self, identity):
        with self._lock:
            record = self._jobs.get(identity)
            if record is None:
                raise KeyError('计算记录已过期')
            if record['state'] != 'succeeded':
                raise ValueError('该任务尚未成功完成')
            return copy.deepcopy(record['result'])

    def operation(self, identity):
        with self._lock:
            if identity not in self._operations:
                raise KeyError('操作已过期')
            return copy.deepcopy({k: v for k, v in self._operations[identity].items() if not k.startswith('_')})

    def cancel_operation(self, identity):
        """Cancel one action/export/chart without invalidating the solved run."""
        with self._lock:
            record = self._operations.get(identity)
            if record is None:
                raise KeyError('操作已过期')
            if record['state'] in ('queued', 'running'):
                self._operation_cancellations[record['_cancellation_slot']] = record['_operation_token']
                record.update(state='cancelled', message='已请求取消此操作；当前设计快照仍可使用')
            return self.operation(identity)

    def _remove_operation(self, identity):
        record = self._operations.pop(identity)
        # Charts and reports may share cached files. Only action-ID-owned PNGs
        # can be removed when their operation record is pruned.
        result = record.get('result') or {}
        if record['kind'] == 'action' and result.get('path'):
            path = Path(result['path']).resolve()
            expected = self.root/record['job_id']/('action-'+identity+'.png')
            if path == expected and path.is_relative_to(self.root):
                path.unlink(missing_ok=True)

    def file(self, identity):
        with self._lock:
            record = copy.deepcopy(self._operations.get(identity) or self._jobs.get(identity))
        if record is None: raise KeyError('文件任务不存在')
        if record['state'] != 'succeeded' or not record.get('result',{}).get('path'):
            raise ValueError('文件尚未生成')
        path = Path(record['result']['path']).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise KeyError('文件已过期')
        return path, record['result'].get('media_type','application/octet-stream')

    def cancel(self, identity):
        with self._lock:
            record = self._jobs.get(identity)
            if record is None:
                raise KeyError('计算记录已过期')
            if record['state'] in ('queued','running'):
                if identity == self.current_id:
                    with self._generation.get_lock():
                        self._generation.value += 1
                record.update(state='cancelled',message='已请求取消；底层数值调用完成后生效')
            return self.status(identity)

    def _receive(self):
        while not self._closed:
            try:
                message = self._outbox.get(timeout=.2)
            except queue.Empty:
                if self._process is not None and not self._process.is_alive():
                    with self._lock:
                        for identity,future in list(self._futures.items()):
                            if not future.done():
                                future.set_exception(RuntimeError('计算进程已退出，请重新提交计算'))
                            record = self._jobs.get(identity) or self._operations.get(identity)
                            if record and record['state'] in ('queued','running'):
                                record.update(state='failed',error=dict(code='worker_exit',message='计算进程已退出，请重新计算'))
                        self._futures.clear()
                continue
            with self._lock:
                identity,event = message['id'],message['event']
                record = self._jobs.get(identity) or self._operations.get(identity)
                future = self._futures.get(identity)
                if record is None:
                    if event in ('done','error','cancelled'):
                        if future and not future.done():
                            future.cancel()
                        self._futures.pop(identity, None)
                    continue
                if record['state'] == 'cancelled':
                    if event in ('done','error','cancelled'):
                        # A cancellation can arrive after the worker's final
                        # check. Do not leak a completed-but-discarded action.
                        if event == 'done' and record.get('kind') == 'action':
                            record['result'] = message['result']
                            result_path = Path(message['result'].get('path', '')).resolve()
                            expected = self.root/record['job_id']/('action-'+identity+'.png')
                            if result_path == expected:
                                result_path.unlink(missing_ok=True)
                        if future and not future.done():
                            future.cancel()
                        self._futures.pop(identity,None)
                    continue
                if event == 'started':
                    record.update(state='running',message='计算中：固定硬件、工作点、损耗与环路')
                elif event == 'progress':
                    record.update(progress=min(95, int(80*message['done']/max(1,message['total']))),
                                  message=message['label'] if record.get('kind') == 'action' else '已解析 '+message['label']+'，正在准备报告数据')
                elif event == 'done':
                    record.update(state='succeeded',result=message['result'],progress=100,message='计算完成')
                    if future and not future.done():
                        future.set_result(message['result'])
                    self._futures.pop(identity,None)
                elif event in ('error','cancelled'):
                    error=message.get('error',dict(code='cancelled',message='计算已取消'))
                    record.update(state='cancelled' if event=='cancelled' else 'failed',error=error)
                    if future and not future.done():
                        future.set_exception(ValueError(error['message']))
                    self._futures.pop(identity,None)

    def _remove_owned(self, job_id):
        path=(self.root/job_id).resolve()
        if path.parent != self.root:
            raise ValueError('Invalid owned runtime path')
        if path.exists():
            shutil.rmtree(path,ignore_errors=True)
        for identity,record in list(self._operations.items()):
            if record['job_id']==job_id and record['state'] not in ('queued','running'):
                self._operations.pop(identity,None)

    def close(self):
        if self._closed:
            return
        self._closed=True
        with self._generation.get_lock():
            self._generation.value += 1
        try:
            self._inbox.put_nowait(None)
        except queue.Full:
            pass
        if self._process:
            self._process.join(3)
            if self._process.is_alive():
                self._process.terminate(); self._process.join(3)
        with self._lock:
            for future in self._futures.values():
                future.cancel()
            self._futures.clear()
        if self._reader:
            self._reader.join(1)
        # No consumer remains after shutdown/termination. A large pending spec
        # can otherwise keep Queue's feeder finalizer waiting forever at exit.
        self._inbox.cancel_join_thread()
        self._outbox.cancel_join_thread()
        self._inbox.close(); self._outbox.close()
        self._temporary.cleanup()
