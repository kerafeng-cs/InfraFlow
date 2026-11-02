"""Nạp catalog (registry + component + blueprint).

- Từ mã nguồn (YAML) khi chạy CLI: load_from_repo().
- Từ bản đóng gói JSON khi chạy trong Lambda/CodeBuild (không cần PyYAML): load_bundle().
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Catalog:
    registry: dict
    components: dict = field(default_factory=dict)  # "name@version" -> manifest (+ "_dir")
    blueprints: dict = field(default_factory=dict)  # "name@version" -> manifest

    def component(self, ref: str) -> dict:
        if ref not in self.components:
            raise KeyError(f"component không có trong catalog: {ref}")
        return self.components[ref]

    def blueprint(self, ref: str) -> dict:
        if ref not in self.blueprints:
            raise KeyError(f"blueprint không có trong catalog: {ref}")
        return self.blueprints[ref]

    def to_json(self) -> str:
        data = {"registry": self.registry, "components": self.components, "blueprints": self.blueprints}
        return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1)


def load_from_repo(root: str | os.PathLike) -> Catalog:
    import yaml  # chỉ cần khi chạy CLI từ mã nguồn

    root = Path(root)
    registry = yaml.safe_load((root / "ics" / "registry.yaml").read_text(encoding="utf-8"))
    cat = Catalog(registry=registry)

    for path in sorted((root / "components").glob("*/*/component.yaml")):
        m = yaml.safe_load(path.read_text(encoding="utf-8"))
        c = m["component"]
        m["_dir"] = path.parent.relative_to(root).as_posix()
        cat.components[f"{c['name']}@{c['version']}"] = m

    for path in sorted((root / "blueprints").glob("*/*/blueprint.yaml")):
        m = yaml.safe_load(path.read_text(encoding="utf-8"))
        b = m["blueprint"]
        cat.blueprints[f"{b['name']}@{b['version']}"] = m

    return cat


def load_bundle(path: str | os.PathLike | None = None) -> Catalog:
    if path is None:
        path = Path(__file__).resolve().parent.parent / "catalog.json"
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Catalog(registry=data["registry"], components=data["components"], blueprints=data["blueprints"])
