from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

UPSTREAM_PACKAGE = "_dreamrain_autopcr_upstream"


def get_upstream_root() -> Path:
    return Path(__file__).parents[2] / "submodule" / "autopcr" / "autopcr"


def import_upstream_package() -> str:
    """Load the autopcr submodule package under a private, non-conflicting name."""

    install_distutils_shim()
    if UPSTREAM_PACKAGE in sys.modules:
        return UPSTREAM_PACKAGE

    package_root = get_upstream_root()
    init_file = package_root / "__init__.py"
    if not init_file.exists():
        raise ModuleNotFoundError(f"autopcr submodule package not found at {package_root}")

    spec = importlib.util.spec_from_file_location(
        UPSTREAM_PACKAGE,
        init_file,
        submodule_search_locations=[str(package_root)],
    )
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"cannot load autopcr submodule package from {init_file}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[UPSTREAM_PACKAGE] = module
    spec.loader.exec_module(module)
    return UPSTREAM_PACKAGE


def upstream_import(module: str):
    package = import_upstream_package()
    return importlib.import_module(f"{package}.{module}")


def install_distutils_shim() -> None:
    """Provide the tiny distutils API used by upstream autopcr on Python 3.12."""

    try:
        importlib.import_module("distutils.util")
        return
    except ModuleNotFoundError:
        pass

    distutils_module = sys.modules.setdefault("distutils", types.ModuleType("distutils"))
    util_module = types.ModuleType("distutils.util")

    def strtobool(value: str) -> bool:
        value = str(value).lower()
        if value in {"y", "yes", "t", "true", "on", "1"}:
            return True
        if value in {"n", "no", "f", "false", "off", "0"}:
            return False
        raise ValueError(f"invalid truth value {value!r}")

    util_module.strtobool = strtobool  # type: ignore[attr-defined]
    distutils_module.util = util_module  # type: ignore[attr-defined]
    sys.modules["distutils.util"] = util_module


@contextmanager
def _pydantic_v1_imports() -> Iterator[None]:
    """Temporarily make upstream autopcr's pydantic v1 imports resolve."""

    import pydantic
    from pydantic import v1 as pydantic_v1
    import pydantic.v1.class_validators as class_validators
    import pydantic.v1.fields as fields
    import pydantic.v1.generics as generics
    import pydantic.v1.main as main
    import pydantic.v1.validators as validators

    attr_names = ("BaseModel", "Field")
    saved_attrs = {name: getattr(pydantic, name, None) for name in attr_names}
    saved_modules = {
        name: sys.modules.get(name)
        for name in (
            "pydantic.class_validators",
            "pydantic.fields",
            "pydantic.generics",
            "pydantic.main",
            "pydantic.validators",
        )
    }

    pydantic.BaseModel = pydantic_v1.BaseModel  # type: ignore[assignment]
    pydantic.Field = pydantic_v1.Field  # type: ignore[assignment]
    sys.modules["pydantic.class_validators"] = class_validators
    sys.modules["pydantic.fields"] = fields
    sys.modules["pydantic.generics"] = generics
    sys.modules["pydantic.main"] = main
    sys.modules["pydantic.validators"] = validators

    try:
        yield
    finally:
        for name, value in saved_attrs.items():
            if value is None:
                delattr(pydantic, name)
            else:
                setattr(pydantic, name, value)
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def warm_up_autopcr_legacy_imports() -> None:
    """Import pydantic-v1-era autopcr modules under a scoped compatibility layer."""

    package = import_upstream_package()
    modules = (
        "model.modelbase",
        "model.common",
        "model.custom",
        "model.requests",
        "model.responses",
        "model.sdkrequests",
        "model.handlers",
        "db.assetmgr",
    )
    with _pydantic_v1_imports():
        for module in modules:
            importlib.import_module(f"{package}.{module}")
