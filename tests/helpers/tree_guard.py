import fnmatch
from pathlib import Path

EXCLUDED_DIRS = {
    ".git",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "htmlcov",
    "node_modules",
}

# Test-run artefacts written into the project root. Matched against the file name
# only at depth 1, so a stray src/.coverage would still be reported.
#
# ".coverage.*" covers the per-process data files coverage writes under
# `parallel = True` or pytest-xdist (.coverage.<host>.<pid>.<random>). It must keep
# the literal dot: a ".coverage*" glob would also swallow .coveragerc, which is a
# tracked project file the guard is supposed to watch.
EXCLUDED_ROOT_FILES = (
    ".coverage",
    ".coverage.*",
)


def snapshot(root: Path):
    result = {}
    root = root.resolve()

    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if len(relative.parts) >= 2 and relative.parts[0] == "tests" and relative.parts[1] == "fixtures":
            continue
        if len(relative.parts) == 1 and any(
            fnmatch.fnmatch(relative.name, pattern) for pattern in EXCLUDED_ROOT_FILES
        ):
            continue
        if path.is_file():
            stat = path.stat()
            result[str(relative)] = (stat.st_size, stat.st_mtime_ns)

    return result


def diff(before, after):
    before_keys = set(before)
    after_keys = set(after)

    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    modified = sorted(
        key for key in before_keys & after_keys if before[key] != after[key]
    )

    return added, removed, modified
