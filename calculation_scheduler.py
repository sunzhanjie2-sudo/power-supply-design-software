"""Latest-only numerical jobs, isolated from Tk and Matplotlib.

The mailbox contains at most one pending request.  Editing parameters cancels
obsolete work cooperatively; an already running library call may finish, but
its result can never be published after a newer generation is requested.
"""
from collections import OrderedDict
import copy
from dataclasses import dataclass
import json
import queue
import sys
import threading
import time


class CalculationCancelled(Exception):
    """Internal control flow, never a failed electrical design."""


_CURRENT = threading.local()


def current_calculation_cancelled():
    """Safe cancellation hook for long numerical loops (also outside workers)."""
    predicate = getattr(_CURRENT, 'cancelled', None)
    return bool(predicate and predicate())


def check_calculation_cancelled():
    if current_calculation_cancelled():
        raise CalculationCancelled()
    yield_at = getattr(_CURRENT, 'ui_yield_at', None)
    if yield_at is not None and time.monotonic() >= yield_at:
        # Tiny NumPy/Python iterations can repeatedly win the GIL while Tk is
        # returning from Tcl calls. Give the UI a short, bounded opportunity
        # to process input. Only GUI workers opt in; batch/web solves do not
        # sleep, and no solver sample or convergence tolerance is changed.
        time.sleep(.001)
        _CURRENT.ui_yield_at = time.monotonic() + .012
        if current_calculation_cancelled():
            raise CalculationCancelled()


def parameter_signature(parameters):
    """Stable cache key; presentation-only metadata is not a calculation input."""
    def plain(value):
        if isinstance(value, dict):
            return {str(k): plain(v) for k, v in value.items()
                    if not str(k).startswith('__') and k != '_cancelled'}
        if isinstance(value, (tuple, list)):
            return [plain(v) for v in value]
        if hasattr(value, 'item'):
            return value.item()
        return value
    return json.dumps(plain(parameters), sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class CalculationResult:
    generation: int
    kind: str
    parameters: dict
    value: object = None
    error: Exception = None
    cached: bool = False


def _snapshot_bytes(value, *, limit=None):
    """Estimate independently deep-copied numerical data without copying it.

    Repeated references to the same object are counted only once, as in
    ``deepcopy``.  Numeric ndarray views are charged for their own copied data,
    not a potentially much larger original backing array.  NumPy is deliberately
    not imported here: the scheduler is also used before scientific imports.
    A limit makes rejecting oversized containers cheap and memory bounded.
    """
    seen = set()
    total = 0

    def visit(item):
        nonlocal total
        identity = id(item)
        if identity in seen:
            return
        seen.add(identity)
        size = sys.getsizeof(item)
        is_array = (hasattr(item, 'nbytes') and hasattr(item, 'dtype')
                    and hasattr(item, 'shape'))
        if is_array:
            # getsizeof includes the storage only for an owning ndarray.
            storage = int(item.nbytes)
            header = size - storage if item.flags.owndata else size
            total += storage + max(0, header)
        else:
            total += size
        if limit is not None and total > limit:
            return
        if isinstance(item, dict):
            for key, val in item.items():
                visit(key)
                visit(val)
                if limit is not None and total > limit:
                    break
        elif isinstance(item, (list, tuple, set, frozenset)):
            for val in item:
                visit(val)
                if limit is not None and total > limit:
                    break
        elif is_array:
            # Ordinary waveforms use numeric dtypes.  An object array also
            # deep-copies its Python payload, so account for those references.
            if item.dtype.hasobject:
                for val in item.flat:
                    visit(val)
                    if limit is not None and total > limit:
                        break
        elif hasattr(item, '__dict__'):
            visit(vars(item))

    visit(value)
    return total


class LatestCalculationWorker:
    """One worker, one pending request, one unread result and a bounded cache.

    Cache limits are both entry-count and estimated retained bytes.  Large
    designs still calculate and publish normally; they simply are not cached.
    """
    def __init__(self, cache_size=3, cache_max_bytes=64 * 1024 * 1024):
        self._condition = threading.Condition()
        self._generation = 0
        self._closed = False
        self._pending = None
        self._active = None
        self._cache = OrderedDict()
        self._cache_size = max(0, int(cache_size))
        self._cache_max_bytes = max(0, int(cache_max_bytes))
        self._cache_sizes = {}
        self._cache_bytes = 0
        self.results = queue.Queue(maxsize=1)
        self._thread = threading.Thread(target=self._run,
                                        name='power-design-calculation', daemon=True)
        self._thread.start()

    @property
    def generation(self):
        with self._condition:
            return self._generation

    @property
    def busy(self):
        with self._condition:
            return self._active is not None or self._pending is not None

    @property
    def cache_bytes(self):
        """Estimated retained cache size; never includes the GUI's live result."""
        with self._condition:
            return self._cache_bytes

    @property
    def cache_entries(self):
        with self._condition:
            return len(self._cache)

    def _discard_results_locked(self):
        """Caller holds generation lock, so no new result can race this drain."""
        retired = []
        try:
            while True:
                retired.append(self.results.get_nowait())
        except queue.Empty:
            return retired

    def is_current(self, generation):
        with self._condition:
            return not self._closed and generation == self._generation

    def invalidate(self):
        with self._condition:
            self._generation += 1
            self._pending = None
            retired = self._discard_results_locked()
            self._condition.notify_all()
            return self._generation

    def submit(self, kind, parameters, function, *, cache=False):
        """function receives an immutable snapshot and a cancellation predicate."""
        snapshot = copy.deepcopy(parameters)
        key = (kind, parameter_signature(snapshot)) if cache else None
        with self._condition:
            if self._closed:
                raise RuntimeError('Calculation worker is closed')
            self._generation += 1
            generation = self._generation
            self._pending = (generation, kind, snapshot, function, key)
            retired = self._discard_results_locked()
            self._condition.notify_all()
            return generation

    def cached(self, kind, parameters):
        key = (kind, parameter_signature(parameters))
        with self._condition:
            result = self._cache.get(key)
            if result is None:
                return None
            self._cache.move_to_end(key)
        # Cache owns its private immutable snapshot.  Eviction can drop that
        # reference while copying, but cannot mutate the object being copied.
        # Never hold the generation/cancellation lock during a large copy.
        return copy.deepcopy(result)

    def remember(self, kind, parameters, value, *, generation=None):
        if not self._cache_size or not self._cache_max_bytes:
            return
        key = (kind, parameter_signature(parameters))
        key_bytes = _snapshot_bytes(key)
        size = _snapshot_bytes(value, limit=self._cache_max_bytes) + key_bytes
        if size > self._cache_max_bytes:
            # Replacing a previously small result must not leave stale data.
            with self._condition:
                if self._closed or (generation is not None and generation != self._generation):
                    return
                retired = self._cache.pop(key, None)
                self._cache_bytes -= self._cache_sizes.pop(key, 0)
            return
        with self._condition:
            if self._closed or (generation is not None and generation != self._generation):
                return
        snapshot = copy.deepcopy(value)
        # Custom deepcopy implementations can grow data, so verify the actual
        # private snapshot too.  Numeric arrays usually give the same estimate.
        size = _snapshot_bytes(snapshot, limit=self._cache_max_bytes) + key_bytes
        retired = []
        with self._condition:
            if self._closed or (generation is not None and generation != self._generation):
                return
            old = self._cache.pop(key, None)
            retired.append(old)
            self._cache_bytes -= self._cache_sizes.pop(key, 0)
            if size <= self._cache_max_bytes:
                self._cache[key] = snapshot
                self._cache_sizes[key] = size
                self._cache_bytes += size
            while (len(self._cache) > self._cache_size
                   or self._cache_bytes > self._cache_max_bytes):
                evicted_key, evicted = self._cache.popitem(last=False)
                self._cache_bytes -= self._cache_sizes.pop(evicted_key)
                retired.append(evicted)
        # Release old arrays / custom finalizers outside the generation lock.
        retired.clear()

    def close(self):
        """Never join from Tk: numerical libraries may still be unwinding."""
        with self._condition:
            self._closed = True
            self._generation += 1
            self._pending = None
            retired_results = self._discard_results_locked()
            retired, self._cache = self._cache, OrderedDict()
            self._cache_sizes.clear()
            self._cache_bytes = 0
            self._condition.notify_all()
        retired.clear()

    def _publish(self, result):
        with self._condition:
            if self._closed or result.generation != self._generation:
                return
            retired = self._discard_results_locked()
            self.results.put_nowait(result)

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed:
                    return
                job, self._pending = self._pending, None
                self._active = job
            try:
                self._execute(job)
            finally:
                # An idle worker must not retain its last full result, input
                # snapshot or callable in the waiting frame's local variables.
                job = None
                with self._condition:
                    self._active = None

    def _execute(self, job):
        generation, kind, parameters, function, key = job
        cancelled = lambda: not self.is_current(generation)
        _CURRENT.cancelled = cancelled
        _CURRENT.ui_yield_at = time.monotonic() + .012
        try:
            value = self.cached(kind, parameters) if key else None
            cached = value is not None
            if not cached:
                check_calculation_cancelled()
                value = function(parameters, cancelled)
                check_calculation_cancelled()
                if key:
                    self.remember(kind, parameters, value, generation=generation)
            self._publish(CalculationResult(generation, kind, parameters,
                                            value=value, cached=cached))
        except CalculationCancelled:
            pass
        except Exception as error:
            # The UI displays the exception message, not its traceback.  Frames
            # can retain a failed solver's full arrays through traceback chains.
            error.__traceback__ = None
            error.__context__ = None
            error.__cause__ = None
            self._publish(CalculationResult(generation, kind, parameters,
                                            error=error))
        finally:
            _CURRENT.cancelled = None
            _CURRENT.ui_yield_at = None


def calculate_efficiency_curve(parameters, cancelled, *, n_pts=12):
    """Batch load points, yielding cancellation between every physical solve."""
    import numpy as np
    from isolated_outputs import scale_load
    from loss_model import compute_design
    fracs = np.linspace(.05, 1.05, n_pts)
    etas, failures = [], []
    for frac in fracs:
        if cancelled():
            raise CalculationCancelled()
        try:
            result = compute_design(scale_load(parameters, frac))
            etas.append(result['eta'])
        except (ValueError, FloatingPointError) as error:
            etas.append(np.nan)
            failures.append((float(frac), str(error)))
    if cancelled():
        raise CalculationCancelled()
    return dict(fracs=fracs, etas=np.asarray(etas), failures=failures)


def calculate_report_efficiency_curve(request, cancelled):
    """Report's original 10–100% grid, computed without a Word/Tk dependency."""
    import math
    import numpy as np
    from isolated_outputs import scale_load
    from loss_model import compute_design
    fracs = np.linspace(.1, 1., 5 if request['coupled'] else 19)
    etas, modes, failures = [], [], []
    for frac in fracs:
        if cancelled():
            raise CalculationCancelled()
        try:
            result = compute_design(scale_load(request['p'], frac))
            etas.append(result['eta'])
            modes.append(result['op']['mode'])
            if not math.isfinite(result['eta']):
                failures.append((float(frac), '磁件 / 损耗结果无效'))
        except CalculationCancelled:
            raise
        except Exception as error:
            etas.append(np.nan)
            modes.append('无效')
            failures.append((float(frac), str(error)))
    if cancelled():
        raise CalculationCancelled()
    return dict(fracs=fracs, etas=np.asarray(etas), modes=modes, failures=failures)


def calculate_optimization(request, cancelled):
    """Numerical sweep/search; cancellation is checked outside exception guards."""
    import numpy as np
    import optimizer as opt
    from isolated_outputs import scale_load
    from loss_model import compute_design
    parameters, frac = request['p'], request['frac']

    def checked_design(specification):
        if cancelled():
            raise CalculationCancelled()
        result = compute_design(specification)
        if cancelled():
            raise CalculationCancelled()
        return result

    if request['kind'] != 'optimize':
        var = request['var']
        opt._check_variables(parameters, [var])
        values = opt.sweep_values(var, request['lo'], request['hi'], request['n'])
        etas = []
        for value in values:
            pp = scale_load(parameters, frac)
            pp[var] = float(value)
            try:
                etas.append(checked_design(pp)['eta'])
            except (ValueError, FloatingPointError):
                etas.append(np.nan)
        return dict(values=values, etas=np.asarray(etas))

    from scipy.optimize import differential_evolution
    variables, bounds = ['f_sw', 'L'], [(20e3, 500e3),
                                      (.5 * parameters['L'], 3 * parameters['L'])]
    opt._check_variables(parameters, variables)

    def objective(vector):
        pp = scale_load(parameters, frac)
        pp.update(zip(variables, map(float, vector)))
        try:
            result = checked_design(pp)
        except (ValueError, FloatingPointError):
            return 1.
        return -result['eta'] + (.25 if result['op']['mode'] == 'DCM' else 0.)

    result = differential_evolution(objective, bounds, seed=0, maxiter=200,
                                    popsize=15, tol=1e-6, polish=True, workers=1)
    best = dict(zip(variables, map(float, result.x)))
    pp = scale_load(parameters, frac)
    pp.update(best)
    try:
        eta = checked_design(pp)['eta']
    except (ValueError, FloatingPointError):
        eta = float('nan')
    return dict(best=best, eta=eta, ok=result.success, fun=result.fun, nit=result.nit)
