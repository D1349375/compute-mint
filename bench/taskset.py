"""The ordered task set.

Tasks are ordered by the number in their id (T01, T02, ...): that is the order in which the
simulated user brings them to the agent, public and private work interleaved. The first half
is the "early" phase and the second half the "late" phase, so the effect of accumulated
review decisions can be compared.
"""
from functools import lru_cache

from .taskmodel import IndexedTask, Task
from .tasks_private import PRIVATE_TASKS
from .tasks_public import PUBLIC_TASKS


def _number(task: Task) -> int:
    return int(task.id[1:3])


@lru_cache(maxsize=1)
def all_tasks() -> tuple[IndexedTask, ...]:
    tasks = sorted(PUBLIC_TASKS + PRIVATE_TASKS, key=_number)
    numbers = [_number(t) for t in tasks]
    if len(set(numbers)) != len(numbers):
        raise ValueError("duplicate task numbers")
    split = (len(tasks) + 1) // 2
    return tuple(IndexedTask(t, i, "early" if i < split else "late") for i, t in enumerate(tasks))


def get_task(task_id: str) -> IndexedTask:
    for it in all_tasks():
        if it.task.id == task_id:
            return it
    raise KeyError(task_id)


def select(ids: list[str] | None = None, limit: int | None = None) -> tuple[IndexedTask, ...]:
    tasks = all_tasks()
    if ids:
        wanted = set(ids)
        tasks = tuple(t for t in tasks if t.task.id in wanted or t.task.id.split("-")[0] in wanted)
    if limit:
        tasks = tasks[:limit]
    return tasks
