"""Server-side query model for bounded cleanup triage metadata."""

from __future__ import annotations

import ntpath
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.cleanup.categories import CATEGORY_LABELS, category_for_name, normalize_extension
from app.cleanup.classification import (
    DO_NOT_TOUCH, REVIEW_REQUIRED, SAFE_ACTIONABLE, CleanupClassificationService,
    cleanup_classifications,
)
from app.intelligence.store import CandidateNotFound
from app.snapshots.store import SnapshotStore, snapshot_store


SORTS = {
    "size_desc": ("size_bytes", True), "mtime_asc": ("mtime", False),
    "name_asc": ("name", False), "path_asc": ("relative_path", False),
}
LOCATIONS = frozenset({
    "downloads", "desktop", "documents", "videos", "pictures", "music", "temporary",
})
CLASSIFICATIONS = frozenset({SAFE_ACTIONABLE, REVIEW_REQUIRED, DO_NOT_TOUCH})


class InvalidTriageQuery(ValueError):
    pass


class TriageSelectionError(ValueError):
    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True)
class TriageQuery:
    locations: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    min_size: int | None = None
    max_size: int | None = None
    older_than_days: int | None = None
    classifications: tuple[str, ...] = ()
    search: str = ""
    sort: str = "size_desc"
    limit: int = 50
    offset: int = 0

    @property
    def explicit_filter(self) -> bool:
        return bool(self.locations or self.categories or self.extensions or
                    self.min_size is not None or self.max_size is not None or
                    self.older_than_days is not None or self.search)


def validate_query(query: TriageQuery) -> TriageQuery:
    locations = tuple(dict.fromkeys(value.casefold() for value in query.locations if value))
    categories = tuple(dict.fromkeys(value.casefold() for value in query.categories if value))
    extensions = tuple(dict.fromkeys(normalize_extension(value) for value in query.extensions if normalize_extension(value)))
    classifications = tuple(dict.fromkeys(value.upper() for value in query.classifications if value))
    if not set(locations) <= LOCATIONS:
        raise InvalidTriageQuery("TRIAGE_LOCATION_INVALID")
    if not set(categories) <= CATEGORY_LABELS.keys():
        raise InvalidTriageQuery("TRIAGE_CATEGORY_INVALID")
    if not set(classifications) <= CLASSIFICATIONS:
        raise InvalidTriageQuery("TRIAGE_CLASSIFICATION_INVALID")
    if query.sort not in SORTS:
        raise InvalidTriageQuery("TRIAGE_SORT_INVALID")
    if query.limit not in {25, 50, 100, 200, 201} or query.offset < 0 or query.offset > 100_000:
        raise InvalidTriageQuery("TRIAGE_PAGE_INVALID")
    if ((query.min_size is not None and query.min_size < 0) or
            (query.max_size is not None and query.max_size < 0) or
            (query.min_size is not None and query.max_size is not None and query.min_size > query.max_size)):
        raise InvalidTriageQuery("TRIAGE_SIZE_INVALID")
    if query.older_than_days is not None and not 0 <= query.older_than_days <= 36_500:
        raise InvalidTriageQuery("TRIAGE_AGE_INVALID")
    search = query.search.strip()
    if len(search) > 200:
        raise InvalidTriageQuery("TRIAGE_SEARCH_INVALID")
    return TriageQuery(locations, categories, extensions, query.min_size, query.max_size,
                       query.older_than_days, classifications, search, query.sort,
                       query.limit, query.offset)


class TriageQueryService:
    def __init__(self, snapshots: SnapshotStore = snapshot_store,
                 classifications: CleanupClassificationService = cleanup_classifications):
        self.snapshots = snapshots
        self.classifications = classifications

    def _latest_snapshot(self, scope_key: str) -> dict[str, object]:
        if scope_key not in {"system_drive_c", "current_user_temp"}:
            raise InvalidTriageQuery("TRIAGE_SCOPE_INVALID")
        with self.snapshots._connection() as connection:
            row = connection.execute("""SELECT * FROM scan_snapshots WHERE scope_key=?
                ORDER BY completed_at DESC, created_at DESC, id DESC LIMIT 1""", (scope_key,)).fetchone()
            if row is None:
                raise CandidateNotFound("TRIAGE_SNAPSHOT_NOT_FOUND")
            return dict(row)

    @staticmethod
    def _public_row(row: dict[str, object], root_path: str) -> dict[str, object]:
        relative = str(row["relative_path"])
        mtime = row.get("mtime")
        age_days = None
        if mtime:
            try:
                age_days = max(0, int((datetime.now(timezone.utc) -
                                       datetime.fromisoformat(str(mtime).replace("Z", "+00:00"))).total_seconds() // 86400))
            except (ValueError, TypeError, OverflowError):
                pass
        return {
            "item_id": row["item_id"], "candidate_id": row["item_id"],
            "relative_path": relative, "display_path": ntpath.join(root_path, relative.replace("/", "\\")),
            "name": row["name"], "extension": row["extension"],
            "size_bytes": int(row["size_bytes"]), "logical_bytes": int(row["size_bytes"]),
            "mtime": mtime, "snapshot_mtime": mtime, "age_days": age_days,
            "category": row["category"], "category_label": CATEGORY_LABELS[row["category"]],
            "location_group": row["location_group"],
            "classification": row["safety_classification"],
            "execution_state": row.get("execution_state", "available"),
        }

    @staticmethod
    def _matches(item: dict[str, object], query: TriageQuery, cutoff: str | None) -> bool:
        if query.locations and item["location_group"] not in query.locations:
            return False
        if query.categories and item["category"] not in query.categories:
            return False
        if query.extensions and item["extension"] not in query.extensions:
            return False
        size = int(item["size_bytes"])
        if query.min_size is not None and size < query.min_size:
            return False
        if query.max_size is not None and size > query.max_size:
            return False
        if query.classifications and item["safety_classification"] not in query.classifications:
            return False
        if cutoff and (not item.get("mtime") or str(item["mtime"]) >= cutoff):
            return False
        if query.search.casefold() not in (str(item["name"]) + " " + str(item["relative_path"])).casefold():
            return False
        return True

    def _temp_rows(self, snapshot: dict[str, object]) -> list[dict[str, object]]:
        run, candidates = self.classifications._latest("current_user_temp")
        if run["snapshot_id"] != snapshot["id"]:
            raise CandidateNotFound("CANDIDATE_RUN_NOT_FOUND")
        rows = []
        for candidate in candidates:
            name = ntpath.basename(str(candidate["relative_path"]))
            decision = self.classifications.decide(candidate, "current_user_temp")
            rows.append({
                "item_id": candidate["candidate_id"], "relative_path": candidate["relative_path"],
                "name": name, "extension": normalize_extension(name),
                "size_bytes": candidate["logical_bytes"], "mtime": candidate.get("snapshot_mtime"),
                "category": category_for_name(name), "location_group": "temporary",
                "safety_classification": decision.classification,
                "execution_state": candidate.get("execution_state", "available"),
            })
        return rows

    def _c_rows(self, snapshot_id: str) -> list[dict[str, object]]:
        with self.snapshots._connection() as connection:
            return [dict(row) for row in connection.execute("""SELECT
                'triage:' || t.id AS item_id, t.relative_path, t.name, t.extension,
                t.size_bytes, t.mtime, t.category, t.location_group,
                t.safety_classification,
                CASE WHEN EXISTS(SELECT 1 FROM cleanup_batch_items bi
                    WHERE bi.candidate_id = 'triage:' || t.id AND bi.execute_result='recycled')
                    THEN 'recycled' ELSE 'available' END AS execution_state
                FROM triage_files t WHERE t.snapshot_id=?""", (snapshot_id,))]

    @staticmethod
    def _sql_filter(query: TriageQuery, cutoff: str | None) -> tuple[str, list[object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        for values, column in ((query.locations, "location_group"),
                               (query.categories, "category"),
                               (query.extensions, "extension"),
                               (query.classifications, "safety_classification")):
            if values:
                clauses.append(f"t.{column} IN ({','.join('?' for _ in values)})")
                parameters.extend(values)
        if query.min_size is not None:
            clauses.append("t.size_bytes >= ?"); parameters.append(query.min_size)
        if query.max_size is not None:
            clauses.append("t.size_bytes <= ?"); parameters.append(query.max_size)
        if cutoff:
            clauses.append("t.mtime IS NOT NULL AND t.mtime < ?"); parameters.append(cutoff)
        if query.search:
            clauses.append("(instr(lower(t.name), lower(?)) > 0 OR instr(lower(t.relative_path), lower(?)) > 0)")
            parameters.extend((query.search, query.search))
        return (" AND " + " AND ".join(clauses) if clauses else ""), parameters

    def _c_query(self, snapshot_id: str, query: TriageQuery, cutoff: str | None):
        where, parameters = self._sql_filter(query, cutoff)
        order = {
            "size_desc": "t.size_bytes DESC, t.relative_path COLLATE NOCASE",
            "mtime_asc": "t.mtime IS NULL, t.mtime ASC, t.relative_path COLLATE NOCASE",
            "name_asc": "t.name COLLATE NOCASE, t.relative_path COLLATE NOCASE",
            "path_asc": "t.relative_path COLLATE NOCASE",
        }[query.sort]
        with self.snapshots._connection() as connection:
            aggregate = connection.execute(
                f"SELECT COUNT(*), COALESCE(SUM(t.size_bytes),0) FROM triage_files t WHERE t.snapshot_id=?{where}",
                (snapshot_id, *parameters)).fetchone()
            rows = [dict(row) for row in connection.execute(f"""SELECT
                'triage:' || t.id AS item_id, t.relative_path, t.name, t.extension,
                t.size_bytes, t.mtime, t.category, t.location_group,
                t.safety_classification,
                CASE WHEN EXISTS(SELECT 1 FROM cleanup_batch_items bi
                    WHERE bi.candidate_id = 'triage:' || t.id AND bi.execute_result='recycled')
                    THEN 'recycled' ELSE 'available' END AS execution_state
                FROM triage_files t WHERE t.snapshot_id=?{where}
                ORDER BY {order} LIMIT ? OFFSET ?""",
                (snapshot_id, *parameters, query.limit, query.offset))]
            facets: dict[str, list[dict[str, object]]] = {}
            for field in ("category", "extension", "location_group"):
                facets[field] = [dict(row) for row in connection.execute(f"""SELECT
                    t.{field} AS value, COUNT(*) AS count, COALESCE(SUM(t.size_bytes),0) AS bytes
                    FROM triage_files t WHERE t.snapshot_id=?{where}
                    GROUP BY t.{field} ORDER BY bytes DESC, value""", (snapshot_id, *parameters))]
            summary = {key: {"count": 0, "bytes": 0} for key in CLASSIFICATIONS}
            for row in connection.execute("""SELECT safety_classification, COUNT(*) AS count,
                COALESCE(SUM(size_bytes),0) AS bytes FROM triage_files WHERE snapshot_id=?
                GROUP BY safety_classification""", (snapshot_id,)):
                summary[row["safety_classification"]] = {"count": row["count"], "bytes": row["bytes"]}
            now = datetime.now(timezone.utc)
            view_specs = (
                ("large_old", "大而且很久未修改", "size_bytes>=? AND mtime IS NOT NULL AND mtime<?", (500*1024**2, (now-timedelta(days=180)).isoformat()), {"min_size":500*1024**2,"older_than_days":180}),
                ("huge", "超大文件", "size_bytes>=?", (5*1024**3,), {"min_size":5*1024**3}),
                ("downloads_large", "下载目录的大文件", "location_group='downloads' AND size_bytes>=?", (500*1024**2,), {"locations":["downloads"],"min_size":500*1024**2}),
                ("old", "很久未修改", "mtime IS NOT NULL AND mtime<?", ((now-timedelta(days=365)).isoformat(),), {"older_than_days":365}),
                ("video", "视频", "category='video'", (), {"categories":["video"]}),
                ("archive", "压缩包", "category='archive'", (), {"categories":["archive"]}),
                ("disk_image", "磁盘镜像", "category='disk_image'", (), {"categories":["disk_image"]}),
                ("backup", "备份文件", "category='backup'", (), {"categories":["backup"]}),
            )
            views = []
            for key, label, condition, values, filters in view_specs:
                row = connection.execute(f"""SELECT COUNT(*) AS count,
                    COALESCE(SUM(size_bytes),0) AS bytes FROM triage_files
                    WHERE snapshot_id=? AND {condition}""", (snapshot_id, *values)).fetchone()
                views.append({"key":key,"label":label,"count":row["count"],"bytes":row["bytes"],"filters":filters})
        return rows, int(aggregate[0]), int(aggregate[1]), facets, summary, views

    @staticmethod
    def _sort(rows: list[dict[str, object]], sort_key: str) -> None:
        if sort_key == "size_desc":
            rows.sort(key=lambda row: (-int(row["size_bytes"]), str(row["relative_path"]).casefold()))
        elif sort_key == "mtime_asc":
            rows.sort(key=lambda row: (row.get("mtime") is None, str(row.get("mtime") or ""), str(row["relative_path"]).casefold()))
        elif sort_key == "name_asc":
            rows.sort(key=lambda row: (str(row["name"]).casefold(), str(row["relative_path"]).casefold()))
        else:
            rows.sort(key=lambda row: str(row["relative_path"]).casefold())

    @staticmethod
    def _facets(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
        result: dict[str, list[dict[str, object]]] = {}
        for field in ("category", "extension", "location_group"):
            grouped: dict[str, list[int]] = {}
            for row in rows:
                bucket = grouped.setdefault(str(row[field]), [0, 0])
                bucket[0] += 1
                bucket[1] += int(row["size_bytes"])
            result[field] = [{"value": key, "count": value[0], "bytes": value[1]}
                             for key, value in sorted(grouped.items(), key=lambda pair: (-pair[1][1], pair[0]))]
        return result

    @staticmethod
    def _smart_views(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        now = datetime.now(timezone.utc)
        definitions = (
            ("large_old", "大而且很久未修改", lambda r: int(r["size_bytes"]) >= 500*1024**2 and r.get("mtime") and str(r["mtime"]) < (now-timedelta(days=180)).isoformat(), {"min_size": 500*1024**2, "older_than_days": 180}),
            ("huge", "超大文件", lambda r: int(r["size_bytes"]) >= 5*1024**3, {"min_size": 5*1024**3}),
            ("downloads_large", "下载目录的大文件", lambda r: r["location_group"] == "downloads" and int(r["size_bytes"]) >= 500*1024**2, {"locations": ["downloads"], "min_size": 500*1024**2}),
            ("old", "很久未修改", lambda r: r.get("mtime") and str(r["mtime"]) < (now-timedelta(days=365)).isoformat(), {"older_than_days": 365}),
            ("video", "视频", lambda r: r["category"] == "video", {"categories": ["video"]}),
            ("archive", "压缩包", lambda r: r["category"] == "archive", {"categories": ["archive"]}),
            ("disk_image", "磁盘镜像", lambda r: r["category"] == "disk_image", {"categories": ["disk_image"]}),
            ("backup", "备份文件", lambda r: r["category"] == "backup", {"categories": ["backup"]}),
        )
        views = []
        for key, label, predicate, filters in definitions:
            matched = [row for row in rows if predicate(row)]
            views.append({"key": key, "label": label, "count": len(matched),
                          "bytes": sum(int(row["size_bytes"]) for row in matched),
                          "filters": filters})
        return views

    def query(self, scope_key: str, raw_query: TriageQuery) -> dict[str, object]:
        query = validate_query(raw_query)
        snapshot = self._latest_snapshot(scope_key)
        available = scope_key == "current_user_temp" or snapshot.get("triage_index_version") is not None
        if not available:
            return {"scope_key": scope_key, "snapshot_id": snapshot["id"], "index_available": False,
                    "message": "这条历史扫描记录没有整理索引。重新扫描后可使用完整筛选功能。",
                    "coverage": None, "summary": {key: {"count": 0, "bytes": 0} for key in CLASSIFICATIONS},
                    "matched_count": 0, "matched_bytes": 0, "items": [], "facets": {},
                    "smart_views": [], "limit": query.limit, "offset": query.offset,
                    "explicit_filter": query.explicit_filter}
        cutoff = ((datetime.now(timezone.utc) - timedelta(days=query.older_than_days)).isoformat()
                  if query.older_than_days is not None else None)
        if scope_key == "system_drive_c":
            page, matched_count, matched_bytes, facets, summary, smart_views = self._c_query(
                str(snapshot["id"]), query, cutoff)
            fallback_observed = matched_count
        else:
            rows = self._temp_rows(snapshot)
            filtered = [row for row in rows if self._matches(row, query, cutoff)]
            self._sort(filtered, query.sort)
            page = filtered[query.offset:query.offset + query.limit]
            matched_count = len(filtered)
            matched_bytes = sum(int(row["size_bytes"]) for row in filtered)
            facets = self._facets(filtered)
            summary = {key: {"count": 0, "bytes": 0} for key in CLASSIFICATIONS}
            for row in rows:
                bucket = summary[str(row["safety_classification"])]
                bucket["count"] += 1; bucket["bytes"] += int(row["size_bytes"])
            smart_views = self._smart_views(rows)
            fallback_observed = len(rows)
        items = [self._public_row(row, str(snapshot["root_path"])) for row in page]
        observed = int(snapshot.get("triage_observed_count") or fallback_observed)
        persisted = int(snapshot.get("triage_persisted_count") or fallback_observed)
        return {
            "scope_key": scope_key, "snapshot_id": snapshot["id"], "index_available": True,
            "coverage": {"observed_count": observed, "persisted_count": persisted,
                         "limit": snapshot.get("triage_index_limit") or snapshot.get("file_persistence_limit"),
                         "status": snapshot.get("triage_coverage") or snapshot.get("coverage")},
            "summary": summary, "matched_count": matched_count,
            "matched_bytes": matched_bytes,
            "items": items, "facets": facets,
            "smart_views": smart_views, "limit": query.limit,
            "offset": query.offset, "explicit_filter": query.explicit_filter,
        }

    def select_filtered(self, scope_key: str, raw_query: TriageQuery) -> dict[str, object]:
        query = validate_query(raw_query)
        if not query.explicit_filter:
            raise TriageSelectionError("TRIAGE_FILTER_REQUIRED")
        result = self.query(scope_key, TriageQuery(
            query.locations, query.categories, query.extensions, query.min_size,
            query.max_size, query.older_than_days, query.classifications, query.search,
            query.sort, 201, 0,
        ))
        if int(result["matched_count"]) > 200:
            raise TriageSelectionError("TRIAGE_SELECTION_TOO_LARGE", 409)
        if any(item["classification"] == DO_NOT_TOUCH for item in result["items"]):
            raise TriageSelectionError("TRIAGE_PROTECTED_SELECTION_BLOCKED")
        return {"item_ids": [item["item_id"] for item in result["items"]],
                "matched_count": result["matched_count"], "matched_bytes": result["matched_bytes"]}


triage_query_service = TriageQueryService()
