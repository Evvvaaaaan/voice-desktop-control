from collections import defaultdict


class HotCommandCache:
    MAX_CACHE_SIZE = 10
    MIN_HITS_FOR_CACHE = 3

    def __init__(self):
        self._freq: dict[str, int] = defaultdict(int)
        self._cache: dict[str, tuple[str, int]] = {}

    def get(self, command: str) -> str | None:
        if command in self._cache:
            action, hits = self._cache[command]
            self._cache[command] = (action, hits + 1)
            return action
        return None

    def record(self, command: str, action: str) -> None:
        self._freq[command] += 1
        if self._freq[command] >= self.MIN_HITS_FOR_CACHE:
            self._cache[command] = (action, self._freq[command])
            if len(self._cache) > self.MAX_CACHE_SIZE:
                least = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[least]
