"""Compare stored metadata from the same logical scan scope."""

from collections import Counter


MIN_RATIO_TARGET_BYTES = 1_048_576
MIN_RATIO_BASE_BYTES = 262_144
RANK_LIMIT = 20
CHANGE_LIST_LIMIT = 100


def delta_ratio(base: int, target: int) -> float | None:
    if base > 0:
        return (target - base) / base
    return 0.0 if target == 0 else None


def compare_directories(
    base_rows: list[dict[str, object]], target_rows: list[dict[str, object]],
) -> dict[str, object]:
    base = {str(row["relative_path"]): row for row in base_rows}
    target = {str(row["relative_path"]): row for row in target_rows}
    changes: list[dict[str, object]] = []
    for path in base.keys() | target.keys():
        before = base.get(path)
        after = target.get(path)
        base_bytes = int(before["subtree_bytes"]) if before else 0
        target_bytes = int(after["subtree_bytes"]) if after else 0
        difference = target_bytes - base_bytes
        if before is None:
            kind = "added"
        elif after is None:
            kind = "removed"
        elif difference > 0:
            kind = "grown"
        elif difference < 0:
            kind = "shrunk"
        else:
            kind = "unchanged"
        changes.append({
            "relative_path": path,
            "name": str((after or before)["name"]),
            "base_bytes": base_bytes,
            "target_bytes": target_bytes,
            "delta_bytes": difference,
            "delta_ratio": delta_ratio(base_bytes, target_bytes),
            "change_type": kind,
        })

    # The root record is useful for consistency, but it would duplicate the total in rankings.
    ranked = [change for change in changes if change["relative_path"]]
    by_bytes = sorted(
        (change for change in ranked if change["delta_bytes"] > 0),
        key=lambda change: (-change["delta_bytes"], change["relative_path"]),
    )[:RANK_LIMIT]
    by_ratio = sorted(
        (
            change for change in ranked
            if change["delta_bytes"] > 0
            and change["target_bytes"] >= MIN_RATIO_TARGET_BYTES
            and change["base_bytes"] >= MIN_RATIO_BASE_BYTES
            and change["delta_ratio"] is not None
        ),
        key=lambda change: (-change["delta_ratio"], -change["delta_bytes"], change["relative_path"]),
    )[:RANK_LIMIT]
    display_changes = sorted(
        ranked, key=lambda change: (-abs(change["delta_bytes"]), change["relative_path"])
    )[:CHANGE_LIST_LIMIT]
    return {
        "directory_change_total": len(ranked),
        "directory_change_counts": dict(Counter(change["change_type"] for change in ranked)),
        "directory_changes": display_changes,
        "growth_by_bytes": by_bytes,
        "growth_by_ratio": by_ratio,
    }


def compare_top_files(
    base_rows: list[dict[str, object]], target_rows: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    base = {str(row["relative_path"]): row for row in base_rows}
    target = {str(row["relative_path"]): row for row in target_rows}
    groups: dict[str, list[dict[str, object]]] = {
        "new_large_files": [], "removed_large_files": [],
        "grown_large_files": [], "shrunk_large_files": [],
    }
    for path in base.keys() | target.keys():
        before = base.get(path)
        after = target.get(path)
        base_bytes = int(before["size_bytes"]) if before else 0
        target_bytes = int(after["size_bytes"]) if after else 0
        if before is None:
            group = "new_large_files"
        elif after is None:
            group = "removed_large_files"
        elif target_bytes > base_bytes:
            group = "grown_large_files"
        elif target_bytes < base_bytes:
            group = "shrunk_large_files"
        else:
            continue
        groups[group].append({
            "relative_path": path,
            "name": str((after or before)["name"]),
            "base_bytes": base_bytes,
            "target_bytes": target_bytes,
            "delta_bytes": target_bytes - base_bytes,
            "change_type": group,
        })
    for group in groups:
        groups[group].sort(key=lambda item: (-abs(item["delta_bytes"]), item["relative_path"]))
        groups[group] = groups[group][:CHANGE_LIST_LIMIT]
    return groups
