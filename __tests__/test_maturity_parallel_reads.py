"""Maturity cache misses overlap reads without changing scope/cache semantics."""
import contextvars
import threading
import unittest
from concurrent.futures import wait as real_wait
from datetime import datetime, timezone
from unittest.mock import patch

import maturity_engine as maturity


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 2, tzinfo=timezone.utc)


def signal_rows(path):
    if path.startswith('/businesses?'):
        return [{'created_at': '2026-03-16T00:00:00Z'}]
    for table, count in [('custom_modules', 5), ('module_entries', 80),
                         ('contacts', 12), ('invoices', 20)]:
        if path.startswith('/' + table + '?'):
            return [{'id': i} for i in range(count)]
    raise AssertionError(path)


class ParallelSignalsTests(unittest.TestCase):
    def test_reads_overlap_with_exact_scope_and_isolated_caller_context(self):
        trace = contextvars.ContextVar('test_maturity_trace', default=None)
        for biz in ('business-a', 'business-b'):
            barrier = threading.Barrier(5, timeout=5)
            seen = []
            lock = threading.Lock()

            def read(path):
                with lock:
                    seen.append((path, trace.get(), maturity.sb_clients._user_jwt_ctx.get()))
                barrier.wait()  # Serial reads cannot complete this rendezvous.
                return signal_rows(path)

            token = trace.set('trace-' + biz)
            try:
                with maturity.sb_clients.with_user_jwt('jwt-' + biz), \
                     patch.object(maturity.sb_clients, 'sb_get_as_service', side_effect=read), \
                     patch.object(maturity, 'datetime', FixedDateTime):
                    result = maturity.collect_signals(biz)
            finally:
                trace.reset(token)
            self.assertEqual(result, dict(age_days=200, module_count=5, entry_count=80,
                                          contact_count=12, paid_invoice_count=20))
            self.assertEqual({path for path, _, _ in seen}, {
                f'/businesses?id=eq.{biz}&select=created_at&limit=1',
                f'/custom_modules?business_id=eq.{biz}&is_active=eq.true&select=id&limit=200',
                f'/module_entries?business_id=eq.{biz}&select=id&limit=200',
                f'/contacts?business_id=eq.{biz}&select=id&limit=200',
                f'/invoices?business_id=eq.{biz}&status=eq.paid&select=id&limit=200',
            })
            self.assertEqual([(trace_id, jwt) for _, trace_id, jwt in seen],
                             [('trace-' + biz, 'jwt-' + biz)] * 5)
        self.assertIsNone(trace.get())
        self.assertIsNone(maturity.sb_clients._user_jwt_ctx.get())

    def test_fresh_cache_does_not_collect_or_write(self):
        cached = dict(stage='operating', signals={'age_days': 50},
                      computed_at='2999-01-01T00:00:00Z')
        with patch.object(maturity.sb_clients, 'sb_get_as_service',
                          return_value=[{'settings': {'maturity': cached}}]) as read, \
             patch.object(maturity, 'collect_signals') as collect, \
             patch.object(maturity.sb_clients, 'sb_patch_as_service') as write:
            result = maturity.compute_maturity('business-a')
        read.assert_called_once_with('/businesses?id=eq.business-a&select=settings&limit=1')
        collect.assert_not_called()
        write.assert_not_called()
        self.assertTrue(result['cached'])
        self.assertEqual(maturity.CACHE_TTL_SECONDS, 6 * 3600)

    def test_cache_write_waits_for_all_signals_and_preserves_fresh_settings(self):
        barrier = threading.Barrier(5, timeout=5)
        completed = set()
        lock = threading.Lock()
        settings_reads = []

        def read(path):
            if 'select=settings' in path:
                settings_reads.append(path)
                if len(settings_reads) == 1:
                    return [{'settings': {'unrelated': 'old'}}]
                self.assertEqual(len(completed), 5)
                return [{'settings': {'unrelated': 'fresh'}}]
            rows = signal_rows(path)
            barrier.wait()
            with lock:
                completed.add(path)
            return rows

        def write(path, body):
            self.assertEqual(len(completed), 5)
            self.assertEqual(path, '/businesses?id=eq.business-a')
            self.assertEqual(body['settings']['unrelated'], 'fresh')
            self.assertEqual(body['settings']['maturity']['stage'], 'scaling')
            self.assertEqual(body['settings']['maturity']['signals']['contact_count'], 12)
            return [{}]

        with patch.object(maturity.sb_clients, 'sb_get_as_service', side_effect=read), \
             patch.object(maturity.sb_clients, 'sb_patch_as_service', side_effect=write) as patch_db, \
             patch.object(maturity, 'datetime', FixedDateTime):
            result = maturity.compute_maturity('business-a')
        patch_db.assert_called_once()
        self.assertEqual(len(settings_reads), 2)
        self.assertEqual(result['stage'], 'scaling')
        self.assertFalse(result['cached'])

    def test_missing_signal_rows_keep_soft_failure_behavior(self):
        with patch.object(maturity.sb_clients, 'sb_get_as_service', return_value=None):
            self.assertEqual(maturity.collect_signals('business-a'), dict(
                age_days=0, module_count=0, entry_count=0, contact_count=0, paid_invoice_count=0))

    def test_unexpected_failure_drains_reads_before_propagation_without_cache_write(self):
        barrier = threading.Barrier(5, timeout=5)
        release = threading.Event()
        drained = threading.Event()

        def read(path):
            barrier.wait()
            if path.startswith('/businesses?'):
                raise RuntimeError('unexpected transport failure')
            if path.startswith('/contacts?'):
                self.assertTrue(release.wait(5))
                drained.set()
            return []

        def drain(futures):
            release.set()
            return real_wait(futures)

        try:
            with patch.object(maturity.sb_clients, 'sb_get_as_service', side_effect=read), \
                 patch.object(maturity, 'wait', side_effect=drain) as waiting, \
                 patch.object(maturity, '_write_cache') as write:
                with self.assertRaisesRegex(RuntimeError, 'unexpected transport failure'):
                    maturity.compute_maturity('business-a', force=True)
                self.assertTrue(drained.is_set())
                waiting.assert_called_once()
                write.assert_not_called()
        finally:
            release.set()

    def test_cache_write_failure_remains_nonfatal(self):
        with patch.object(maturity.sb_clients, 'sb_get_as_service', return_value=[]), \
             patch.object(maturity, '_write_cache', side_effect=RuntimeError('write failed')):
            result = maturity.compute_maturity('business-a', force=True)
        self.assertEqual(result['stage'], 'idea')
        self.assertFalse(result['cached'])


if __name__ == '__main__':
    unittest.main()
