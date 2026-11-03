from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_network_core(path: Path) -> ModuleType:
    """Load the network solver module without modifying the solver file."""
    source = path.resolve(strict=True)
    module_name = f"evflex_legacy_network_{source.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load legacy network core: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module

def configure_core(core: ModuleType, repo_root: Path) -> None:
    """Point the archived network core at the final feeder inputs."""
    repo = repo_root.resolve(strict=True)
    masters = {
        "ieee13": repo / "data" / "feeders" / "ieee13" / "IEEE13Nodeckt.dss",
        "lv906": repo / "data" / "feeders" / "lv906_core" / "MasterStaticAudit.dss",
    }
    for feeder, master in masters.items():
        if feeder not in core.FEEDERS:
            raise KeyError(f"Legacy core has no feeder configuration for {feeder}")
        core.FEEDERS[feeder]["master"] = master.resolve(strict=True)
    core.FEEDERS["ieee13"]["kva_limit"] = 5000.0
    core.FEEDERS["lv906"]["kva_limit"] = 800.0
