from pathlib import PurePosixPath


# Exact path-component prefixes, applied only when scanning the project workspace.
PROJECT_EXCLUSIONS: tuple[tuple[str, ...], ...] = (
    (".git",),
    (".venv",),
    ("frontend", "node_modules"),
    ("frontend", "dist"),
    ("logs",),
    ("data",),
)


def project_exclusion(relative_path: str) -> str | None:
    parts = tuple(part.casefold() for part in PurePosixPath(relative_path).parts)
    for rule in PROJECT_EXCLUSIONS:
        if parts[:len(rule)] == rule:
            return "/".join(rule)
    return None
