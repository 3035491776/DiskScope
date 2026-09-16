"""Pure candidate generation from snapshot rows; never touches scan targets."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import PureWindowsPath
from typing import Iterable, Mapping

from app.intelligence.rules import (
    CandidateRule, GIB, MIB, RULES, RULE_VERSION, SCOPED_USER_TEMP_RULES,
)


def path_parts(relative_path: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in relative_path.replace("\\", "/").split("/") if part)


def parent_path(relative_path: str) -> str:
    return relative_path.replace("\\", "/").rpartition("/")[0]


def age_days(mtime: str | None, completed_at: str) -> float | None:
    if not mtime:
        return None
    try:
        modified = datetime.fromisoformat(mtime.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        if modified.tzinfo is None or completed.tzinfo is None:
            return None
        return max(0.0, (completed - modified).total_seconds() / 86400)
    except ValueError:
        return None


def age_bucket(days: float | None) -> str:
    if days is None:
        return "修改时间不可用"
    if days < 1:
        return "修改时间距扫描完成不足 1 天"
    if days < 7:
        return "修改时间距扫描完成 1–7 天"
    if days < 30:
        return "修改时间距扫描完成 7–30 天"
    if days < 90:
        return "修改时间距扫描完成 30–90 天"
    return "修改时间距扫描完成超过 90 天"


def size_label(size: int) -> str:
    if size >= GIB:
        return f"逻辑大小约 {size / GIB:.1f} GiB"
    return f"逻辑大小约 {size / MIB:.1f} MiB"


def display_path(scope_key: str, relative_path: str, root_path: str = "") -> str:
    normalized = relative_path.replace("/", "\\")
    if scope_key == "system_drive_c":
        return f"C:\\{normalized}"
    if scope_key == "current_user_temp":
        return str(PureWindowsPath(root_path) / PureWindowsPath(normalized))
    return normalized


class RuleEngine:
    """Priority-ordered rules; age is relative to snapshot time for repeatability."""

    def __init__(self, rules: tuple[CandidateRule, ...] = RULES):
        self.rules = tuple(sorted(rules, key=lambda item: (-item.priority, item.rule_id)))
        self.by_type = {
            kind: tuple(rule for rule in self.rules if rule.object_type == kind)
            for kind in ("file", "directory")
        }
        self.scoped_user_temp_rules = SCOPED_USER_TEMP_RULES

    def classify(self, row: Mapping[str, object], object_type: str,
                 snapshot: Mapping[str, object]) -> dict[str, object] | None:
        path = str(row["relative_path"])
        parts = path_parts(path)
        size = int(row["size_bytes"] if object_type == "file" else row["subtree_bytes"])
        scope_key = str(snapshot["scope_key"])
        if not parts or scope_key not in {"system_drive_c", "current_user_temp"}:
            return None
        age = age_days(str(row["mtime"]), str(snapshot["completed_at"])) if object_type == "file" else None
        rules = (self.scoped_user_temp_rules if scope_key == "current_user_temp" and object_type == "file"
                 else self.by_type[object_type] if scope_key == "system_drive_c" else ())
        match = next((rule for rule in rules if rule.matches(parts, object_type, size, age)), None)
        if match is None:
            return None
        evidence = [match.summary, size_label(size)]
        if match.extensions:
            evidence.append(f"文件扩展名为 .{parts[-1].rpartition('.')[2].lower() or '未知'}")
        if object_type == "file":
            evidence.append(age_bucket(age))
        if object_type == "directory" and row.get("coverage") == "limited":
            evidence.append("此目录的扫描覆盖受限，大小可能不完整")
        if match.risk_level == "protected":
            evidence.append("由 Windows 或应用管理，不建议手动处理")
        return {
            "candidate_id": "", "scope_key": str(snapshot["scope_key"]),
            "snapshot_id": str(snapshot["snapshot_id"]), "relative_path": path,
            "display_path": display_path(scope_key, path, str(snapshot.get("root_path", ""))),
            "object_type": object_type, "logical_bytes": size,
            "category": match.category, "risk_level": match.risk_level,
            "confidence": match.confidence, "reason_code": match.reason_code,
            "title": match.title, "summary": match.summary,
            "explanation": match.explanation, "evidence": evidence,
            "recommended_action": match.recommended_action,
            "requires_manual_review": match.risk_level != "protected",
            "source_rule_id": match.rule_id, "rule_version": RULE_VERSION,
            "group_id": None,
        }

    def analyze(self, snapshot: Mapping[str, object], files: Iterable[Mapping[str, object]],
                directories: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for row in files:
            candidate = self.classify(row, "file", snapshot)
            if candidate is not None:
                candidates.append(candidate)
        for row in directories:
            candidate = self.classify(row, "directory", snapshot)
            if candidate is not None:
                candidates.append(candidate)

        dumps: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
        for candidate in candidates:
            if candidate["reason_code"] == "CRASH_DUMP_IN_SERVICE_TEMP":
                key = (str(candidate["reason_code"]), parent_path(str(candidate["relative_path"])), str(candidate["category"]))
                dumps[key].append(candidate)
        grouped_paths: dict[str, str] = {}
        for (_, parent, _), members in sorted(dumps.items()):
            if len(members) < 2:
                continue
            total = sum(int(item["logical_bytes"]) for item in members)
            group = {
                "candidate_id": "", "scope_key": str(snapshot["scope_key"]),
                "snapshot_id": str(snapshot["snapshot_id"]), "relative_path": parent,
                "display_path": display_path(str(snapshot["scope_key"]), parent, str(snapshot.get("root_path", ""))),
                "object_type": "group", "logical_bytes": total,
                "category": "crash_dump", "risk_level": "review", "confidence": "high",
                "reason_code": "CRASH_DUMP_GROUP_IN_SERVICE_TEMP",
                "title": f"系统服务崩溃转储（{len(members)} 项）",
                "summary": "同一系统服务临时目录中的大型诊断转储。",
                "explanation": "这些文件可能仍用于故障诊断；当前版本只展示，不会删除。",
                "evidence": ["成员位于同一系统服务临时目录", f"包含 {len(members)} 个 Top-K 文件", size_label(total)],
                "recommended_action": "review_for_cleanup", "requires_manual_review": True,
                "source_rule_id": "service-temp-dump-group", "rule_version": RULE_VERSION,
                "group_id": None,
            }
            candidates.append(group)
            for member in members:
                grouped_paths[str(member["relative_path"])] = parent

        candidates.sort(key=lambda item: (str(item["object_type"]), str(item["relative_path"]).casefold(), str(item["source_rule_id"])))
        group_ids: dict[str, str] = {}
        for index, candidate in enumerate(candidates):
            candidate_id = f"{snapshot['snapshot_id']}:{RULE_VERSION}:{index:05d}"
            candidate["candidate_id"] = candidate_id
            if candidate["object_type"] == "group":
                group_ids[str(candidate["relative_path"])] = candidate_id
        for candidate in candidates:
            if candidate["object_type"] == "file" and candidate["relative_path"] in grouped_paths:
                candidate["group_id"] = group_ids[grouped_paths[str(candidate["relative_path"])]]
        return candidates
