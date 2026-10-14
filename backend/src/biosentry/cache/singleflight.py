"""Single-flight: concurrent callers that miss on the same key share one computation.

The first caller for a key computes; callers that arrive while it runs wait for its result
(or its exception). Nothing is remembered once the flight lands: the next miss starts a new
flight, so a failure is never cached.
"""

import threading
from collections.abc import Callable, Hashable
from concurrent.futures import Future
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class SingleFlight(Generic[K, V]):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flights: dict[K, Future[V]] = {}

    def run(self, key: K, compute: Callable[[], V]) -> V:
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if flight is None:
                flight = Future()
                self._flights[key] = flight
        if not leader:
            return flight.result()
        try:
            value = compute()
        except BaseException as exc:
            flight.set_exception(exc)
            raise
        else:
            flight.set_result(value)
            return value
        finally:
            with self._lock:
                del self._flights[key]
