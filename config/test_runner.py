from django.test.runner import DiscoverRunner
from django.test.testcases import TransactionTestCase


class MongoDiscoverRunner(DiscoverRunner):
    """MongoDB has no transaction-wrapped TestCase isolation (Django flushes every collection after each test),
    so the rows seeded by data migrations (groups, default Jira statuses) would vanish after the first test.
    Flag every test class with serialized_rollback so Django restores them before each test."""

    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        for test in self._iter_tests(suite):
            if isinstance(test, TransactionTestCase):
                type(test).serialized_rollback = True
        return suite

    def _iter_tests(self, suite):
        for item in suite:
            if hasattr(item, '__iter__'):
                yield from self._iter_tests(item)
            else:
                yield item
