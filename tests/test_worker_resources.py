"""Bound numerical retention, without reducing solver or waveform accuracy."""
import copy
import gc
from pathlib import Path
import sys
import threading
import time
import unittest
import weakref

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculation_scheduler import LatestCalculationWorker, _snapshot_bytes


def wait_idle(worker, timeout=3.):
    deadline = time.monotonic() + timeout
    while worker.busy:
        if time.monotonic() > deadline:
            raise AssertionError('Worker did not finish')
        time.sleep(.002)


class GatedCopy:
    """A test-only slow deepcopy that has no thread locks in its instance."""
    armed = False
    started = threading.Event()
    release = threading.Event()

    def __init__(self, value):
        self.value = value

    def __deepcopy__(self, memo):
        if type(self).armed:
            type(self).started.set()
            type(self).release.wait(3.)
        result = type(self)(copy.deepcopy(self.value, memo))
        memo[id(self)] = result
        return result


class WorkerResourceChecks(unittest.TestCase):
    def setUp(self):
        self.workers = []
        GatedCopy.armed = False
        GatedCopy.started.clear()
        GatedCopy.release.clear()

    def tearDown(self):
        GatedCopy.release.set()
        GatedCopy.armed = False
        for worker in self.workers:
            worker.close()
            worker._thread.join(timeout=3.)

    def worker(self, **kwargs):
        worker = LatestCalculationWorker(**kwargs)
        self.workers.append(worker)
        return worker

    def test_byte_limit_evicts_lru_even_before_entry_count_limit(self):
        worker = self.worker(cache_size=3, cache_max_bytes=30_000)
        for i in range(3):
            worker.remember('design', {'id': i}, {'wave': np.full(1500, i, dtype=float)})
        self.assertEqual(worker.cache_entries, 2)
        self.assertLessEqual(worker.cache_bytes, 30_000)
        self.assertIsNone(worker.cached('design', {'id': 0}))
        np.testing.assert_array_equal(worker.cached('design', {'id': 2})['wave'], 2.)
        worker.cached('design', {'id': 1})
        worker.remember('design', {'id': 3}, {'wave': np.ones(1500)})
        self.assertIsNone(worker.cached('design', {'id': 2}))
        self.assertIsNotNone(worker.cached('design', {'id': 1}))

    def test_oversized_result_publishes_without_copying_into_cache(self):
        worker = self.worker(cache_max_bytes=10_000)
        value = np.arange(100_000, dtype=float)
        worker.submit('design', {}, lambda _p, _c: value, cache=True)
        wait_idle(worker)
        result = worker.results.get_nowait()
        self.assertIs(result.value, value)
        np.testing.assert_array_equal(result.value, value)
        self.assertEqual(worker.cache_entries, 0)
        self.assertEqual(worker.cache_bytes, 0)

    def test_oversized_replacement_removes_old_cached_value(self):
        worker = self.worker(cache_max_bytes=10_000)
        worker.remember('design', {}, np.ones(3))
        worker.remember('design', {}, np.ones(100_000))
        self.assertIsNone(worker.cached('design', {}))
        self.assertEqual(worker.cache_bytes, 0)

    def test_zero_byte_budget_disables_cache(self):
        worker = self.worker(cache_max_bytes=0)
        worker.remember('design', {}, {'value': 1})
        self.assertEqual(worker.cache_entries, 0)
        self.assertEqual(worker.cache_bytes, 0)

    def test_aliases_are_counted_once_and_numpy_views_charge_copied_data(self):
        array = np.zeros(100_000)
        aliased = {'a': array, 'b': array}
        independent = {'a': array, 'b': array.copy()}
        self.assertGreater(_snapshot_bytes(independent) - _snapshot_bytes(aliased),
                           array.nbytes - 1000)
        view = array[::10]
        self.assertLess(_snapshot_bytes(view), view.nbytes + 1000)
        self.assertGreaterEqual(_snapshot_bytes(view), view.nbytes)
        worker = self.worker(cache_max_bytes=100_000)
        worker.remember('design', {}, view)
        self.assertEqual(worker.cache_entries, 1)
        self.assertGreaterEqual(worker.cache_bytes, view.nbytes)

    def test_cache_still_isolates_ui_and_caller_mutations(self):
        worker = self.worker()
        original = {'wave': np.arange(20.), 'settings': [1, 2]}
        worker.remember('design', {}, original)
        original['wave'][0] = -100.
        first = worker.cached('design', {})
        first['wave'][1] = -200.
        first['settings'].append(3)
        second = worker.cached('design', {})
        np.testing.assert_array_equal(second['wave'], np.arange(20.))
        self.assertEqual(second['settings'], [1, 2])

    def test_only_latest_unread_result_is_retained(self):
        worker = self.worker(cache_size=0)
        references = []

        def compute(parameters, _cancelled):
            value = np.full(10_000, parameters['id'], dtype=float)
            references.append(weakref.ref(value))
            return value

        for i in range(8):
            generation = worker.submit('design', {'id': i}, compute)
            wait_idle(worker)
            self.assertEqual(worker.results.qsize(), 1)
        gc.collect()
        self.assertTrue(all(ref() is None for ref in references[:-1]))
        result = worker.results.get_nowait()
        self.assertEqual(result.generation, generation)
        np.testing.assert_array_equal(result.value, 7.)
        self.assertTrue(worker.results.empty())

    def test_invalidation_discards_unread_full_result(self):
        worker = self.worker(cache_size=0)
        reference = []

        def compute(_p, _c):
            value = np.ones(10_000)
            reference.append(weakref.ref(value))
            return value

        worker.submit('design', {}, compute)
        wait_idle(worker)
        worker.invalidate()
        gc.collect()
        self.assertTrue(worker.results.empty())
        self.assertIsNone(reference[0]())

    def test_idle_worker_releases_consumed_result_and_input_snapshot(self):
        worker = self.worker(cache_size=0)
        input_refs, output_refs = [], []

        def compute(parameters, _cancelled):
            input_refs.append(weakref.ref(parameters['wave']))
            value = np.ones(10_000)
            output_refs.append(weakref.ref(value))
            return value

        worker.submit('design', {'wave': np.zeros(10_000)}, compute)
        wait_idle(worker)
        result = worker.results.get_nowait()
        del result
        gc.collect()
        self.assertIsNone(input_refs[0]())
        self.assertIsNone(output_refs[0]())

    def test_close_releases_cache_and_unread_results_without_waiting(self):
        worker = self.worker()
        worker.remember('design', {'id': 1}, np.ones(10_000))
        worker.submit('design', {'id': 2}, lambda _p, _c: np.ones(10_000), cache=True)
        wait_idle(worker)
        self.assertEqual(worker.cache_entries, 2)
        self.assertFalse(worker.results.empty())
        before = time.monotonic()
        worker.close()
        self.assertLess(time.monotonic() - before, .2)
        self.assertEqual(worker.cache_entries, 0)
        self.assertEqual(worker.cache_bytes, 0)
        self.assertTrue(worker.results.empty())
        worker.remember('design', {}, np.ones(10))
        self.assertEqual(worker.cache_entries, 0)

    def test_cached_deepcopy_does_not_hold_generation_lock(self):
        worker = self.worker()
        worker.remember('design', {}, GatedCopy([1]))
        GatedCopy.armed = True
        thread = threading.Thread(target=lambda: worker.cached('design', {}))
        thread.start()
        try:
            self.assertTrue(GatedCopy.started.wait(1.))
            before = time.monotonic()
            worker.invalidate()
            self.assertLess(time.monotonic() - before, .2)
        finally:
            GatedCopy.release.set()
            thread.join(timeout=3.)

    def test_remember_copy_does_not_hold_lock_or_commit_obsolete_generation(self):
        worker = self.worker()
        GatedCopy.armed = True
        generation = worker.generation
        thread = threading.Thread(target=lambda: worker.remember(
            'design', {}, GatedCopy([1]), generation=generation))
        thread.start()
        try:
            self.assertTrue(GatedCopy.started.wait(1.))
            before = time.monotonic()
            worker.invalidate()
            self.assertLess(time.monotonic() - before, .2)
        finally:
            GatedCopy.release.set()
            thread.join(timeout=3.)
        self.assertEqual(worker.cache_entries, 0)

    def test_failure_message_does_not_retain_traceback_waveforms(self):
        worker = self.worker()
        references = []

        def compute(_p, _c):
            value = np.ones(10_000)
            references.append(weakref.ref(value))
            try:
                raise ValueError('inner failure')
            except ValueError as error:
                raise RuntimeError('visible message') from error

        worker.submit('design', {}, compute)
        wait_idle(worker)
        result = worker.results.get_nowait()
        self.assertIsInstance(result.error, RuntimeError)
        self.assertEqual(str(result.error), 'visible message')
        self.assertIsNone(result.error.__traceback__)
        self.assertIsNone(result.error.__context__)
        self.assertIsNone(result.error.__cause__)
        gc.collect()
        self.assertIsNone(references[0]())


if __name__ == '__main__':
    unittest.main(verbosity=2)
