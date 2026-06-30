import json
import os


class RoutineManager:
    def __init__(self, routines_path: str = "data/routines.json"):
        self._path = routines_path
        if not os.path.exists(self._path):
            self._write([])

    def _read(self) -> list:
        with open(self._path) as f:
            return json.load(f)

    def _write(self, data: list) -> None:
        with open(self._path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save(self, name: str, steps: list[dict]) -> None:
        routines = self._read()
        routines = [r for r in routines if r["name"] != name]
        routines.append({"name": name, "steps": steps})
        self._write(routines)

    def load_all(self) -> list[dict]:
        return self._read()

    def execute(self, name: str, executor) -> bool:
        routines = self._read()
        for r in routines:
            if r["name"] == name:
                for step in r["steps"]:
                    if not executor.run(step["action"], step["params"]):
                        return False
                return True
        return False
