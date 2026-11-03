from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_duration_engine(path: Path) -> ModuleType:
    source = path.resolve(strict=True)
    module_name = f"evflex_archived_duration_engine_{source.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load archived duration engine: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module
