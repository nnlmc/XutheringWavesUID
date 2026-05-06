class SingleFlightLock:
    """按 key 的内存触发锁：同一 key 仅允许一个执行流。"""

    def __init__(self):
        self._holding: set[str] = set()

    def acquire(self, key: str) -> bool:
        if key in self._holding:
            return False
        self._holding.add(key)
        return True

    def release(self, key: str) -> None:
        self._holding.discard(key)
