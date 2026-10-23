import pytest

from analytics import _new_stats, _record


@pytest.fixture
def stats_factory():
    def make_stats(touches=''):
        stats = _new_stats()
        for touch in touches.split():
            action, grade = touch
            _record(stats, action, grade)
        return stats

    return make_stats
