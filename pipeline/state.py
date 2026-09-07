"""Run state: one JSON journal per run so every stage is resumable and auditable."""
import json
import os
import time


class RunState:
    def __init__(self, run_dir: str):
        self.run_dir = run_dir
        self.path = os.path.join(run_dir, "state.json")
        os.makedirs(run_dir, exist_ok=True)
        self.data = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "stages": {}, "scans": {}}
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.data = json.load(f)

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)

    def mark_stage(self, name: str, **info) -> None:
        self.data["stages"][name] = {"finished": time.strftime("%Y-%m-%dT%H:%M:%S"), **info}
        self.save()

    def stage_done(self, name: str) -> bool:
        return name in self.data["stages"]

    def scans(self):
        return self.data["scans"]
