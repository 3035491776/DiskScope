"""Server-owned controlled probe creation, registry, and metadata validation."""

from __future__ import annotations

import hashlib
import ntpath
import os
import secrets
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.cleanup.policy import REPARSE_FLAG
from app.snapshots.store import SnapshotStore

PROBE_SIZE = 64 * 1024
PROBE_RULE_VERSION = "CONTROLLED_PROBE_RECYCLE_V1"
PROBE_STATES = frozenset({"created", "prepared", "recycled", "invalidated", "failed"})


def _sqlite_identity(value: int) -> int:
    """Preserve an unsigned Windows file identity in SQLite's signed int64."""
    value = int(value)
    if -(1 << 63) <= value < (1 << 63):
        return value
    if 0 <= value < (1 << 64):
        return value - (1 << 64)
    raise ProbeError("PROBE_FILE_IDENTITY_UNSUPPORTED", 503)


class ProbeError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _canonical_parts(path: str) -> tuple[str, tuple[str, ...]] | None:
    if not isinstance(path, str) or not path or "\x00" in path or "/" in path:
        return None
    if path.startswith(("\\\\", "\\\\?\\", "\\\\.\\")):
        return None
    drive, tail = ntpath.splitdrive(path)
    if len(drive) != 2 or drive[1] != ":" or not tail.startswith("\\"):
        return None
    parts = tail[1:].split("\\")
    if not parts or any(part in {"", ".", ".."} or ":" in part for part in parts):
        return None
    if ntpath.normpath(path).casefold() != path.casefold():
        return None
    return drive.casefold(), tuple(part.casefold() for part in parts)


def _iso_from_ns(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, timezone.utc).isoformat()


class ControlledProbeRegistry:
    def __init__(self, snapshots: SnapshotStore, base_temp: Path, *,
                 session_id: str | None = None):
        self.snapshots = snapshots
        self.base_temp = Path(base_temp)
        self.session_id = session_id or secrets.token_hex(12)
        self.session_root = self.base_temp / "DiskScope" / "probes" / self.session_id

    @classmethod
    def production(cls, snapshots: SnapshotStore) -> "ControlledProbeRegistry":
        profile = os.environ.get("USERPROFILE", "")
        if not profile:
            raise ProbeError("PROBE_USER_PROFILE_UNAVAILABLE", 503)
        profile_parts = _canonical_parts(profile)
        if profile_parts is None or profile_parts[0] != "c:":
            raise ProbeError("PROBE_USER_PROFILE_BLOCKED", 503)
        base_temp = Path(profile) / "AppData" / "Local" / "Temp"
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data and ntpath.normcase(ntpath.normpath(local_app_data)) != ntpath.normcase(
                ntpath.normpath(str(Path(profile) / "AppData" / "Local"))):
            raise ProbeError("PROBE_LOCALAPPDATA_MISMATCH", 503)
        return cls(snapshots, base_temp)

    def _ensure_session_root(self) -> None:
        if not self.base_temp.is_dir():
            raise ProbeError("PROBE_TEMP_ROOT_UNAVAILABLE", 503)
        try:
            root_info = os.lstat(ntpath.splitdrive(str(self.base_temp))[0] + "\\")
            device = root_info.st_dev
            current = Path(ntpath.splitdrive(str(self.base_temp))[0] + "\\")
            for part in _canonical_parts(str(self.base_temp))[1]:
                current /= part
                info = os.lstat(current)
                if (stat.S_ISLNK(info.st_mode) or
                        getattr(info, "st_file_attributes", 0) & REPARSE_FLAG or
                        info.st_dev != device or not stat.S_ISDIR(info.st_mode)):
                    raise ProbeError("PROBE_PARENT_PATH_BLOCKED")
            for part in ("DiskScope", "probes", self.session_id):
                current /= part
                try:
                    os.mkdir(current)
                except FileExistsError:
                    pass
                info = os.lstat(current)
                if (stat.S_ISLNK(info.st_mode) or
                        getattr(info, "st_file_attributes", 0) & REPARSE_FLAG or
                        info.st_dev != device or not stat.S_ISDIR(info.st_mode)):
                    raise ProbeError("PROBE_PARENT_PATH_BLOCKED")
        except ProbeError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise ProbeError("PROBE_DIRECTORY_CREATE_FAILED", 503) from exc

    def create(self) -> dict[str, object]:
        self._ensure_session_root()
        probe_id = str(uuid.uuid4())
        path = self.session_root / f"probe-{uuid.uuid4()}.tmp"
        nonce = secrets.token_bytes(32)
        content = (b"DiskScope controlled recycle acceptance probe\r\n" * 1600)[:PROBE_SIZE]
        content = content.ljust(PROBE_SIZE, b"\0")
        try:
            with open(path, "xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            info = os.lstat(path)
        except OSError as exc:
            raise ProbeError("PROBE_CREATE_FAILED", 503) from exc
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & REPARSE_FLAG):
            raise ProbeError("PROBE_CREATED_OBJECT_INVALID")
        created_at = datetime.now(timezone.utc).isoformat()
        with self.snapshots._connection() as connection:
            connection.execute("""INSERT INTO controlled_probes (
                probe_id, session_id, absolute_path, created_at, expected_size,
                expected_mtime_ns, expected_ctime_ns, expected_device, expected_inode,
                creation_nonce_hash, state, updated_at, failure_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, NULL)""",
                (probe_id, self.session_id, str(path), created_at, info.st_size,
                 info.st_mtime_ns, info.st_ctime_ns,
                 _sqlite_identity(info.st_dev), _sqlite_identity(info.st_ino),
                 hashlib.sha256(nonce).hexdigest(), created_at))
            connection.commit()
        return self.get(probe_id)

    def get(self, probe_id: str, *, current_session_only: bool = True) -> dict[str, object]:
        with self.snapshots._connection() as connection:
            query = "SELECT * FROM controlled_probes WHERE probe_id = ?"
            params: tuple[object, ...] = (probe_id,)
            if current_session_only:
                query += " AND session_id = ?"
                params += (self.session_id,)
            row = connection.execute(query, params).fetchone()
            if row is None:
                raise ProbeError("CONTROLLED_PROBE_NOT_FOUND", 404)
            return dict(row)

    def list_current(self) -> list[dict[str, object]]:
        with self.snapshots._connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM controlled_probes WHERE session_id = ? ORDER BY created_at DESC",
                (self.session_id,))]

    def update_state(self, connection, probe_id: str, state: str,
                     failure_code: str | None = None) -> None:
        if state not in PROBE_STATES:
            raise ValueError("Unknown probe state")
        connection.execute("""UPDATE controlled_probes
            SET state = ?, updated_at = ?, failure_code = ?
            WHERE probe_id = ? AND session_id = ?""",
            (state, datetime.now(timezone.utc).isoformat(), failure_code,
             probe_id, self.session_id))

    def preflight(self, record: dict[str, object], expected_state: str) -> dict[str, object]:
        path = str(record.get("absolute_path", ""))
        reasons: list[str] = []
        checks: list[dict[str, object]] = []
        fingerprint = None
        current = _canonical_parts(path)
        expected_root = _canonical_parts(str(self.session_root))
        if (record.get("session_id") != self.session_id or current is None or
                expected_root is None or current[0] != expected_root[0] or
                current[1][:-1] != expected_root[1] or
                not current[1][-1].startswith("probe-") or
                not current[1][-1].endswith(".tmp")):
            reasons.append("CONTROLLED_PROBE_BOUNDARY_BLOCKED")
        if record.get("state") != expected_state:
            reasons.append("CONTROLLED_PROBE_STATE_BLOCKED")
        if not reasons:
            drive, parts = current
            prefix = drive + "\\"
            try:
                root_info = os.lstat(prefix)
                root_device = root_info.st_dev
                for index, part in enumerate(parts):
                    prefix = ntpath.join(prefix, part)
                    info = os.lstat(prefix)
                    if (stat.S_ISLNK(info.st_mode) or
                            getattr(info, "st_file_attributes", 0) & REPARSE_FLAG):
                        reasons.append("EXECUTION_REPARSE_POINT_BLOCKED")
                        break
                    if info.st_dev != root_device:
                        reasons.append("EXECUTION_CROSS_VOLUME_BLOCKED")
                        break
                    if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                        reasons.append("EXECUTION_PARENT_CHANGED")
                        break
                    if index == len(parts) - 1:
                        if not stat.S_ISREG(info.st_mode):
                            reasons.append("DIRECTORY_EXECUTION_NOT_SUPPORTED")
                            break
                        fingerprint = {
                            "size": info.st_size, "mtime_ns": info.st_mtime_ns,
                            "ctime_ns": info.st_ctime_ns,
                            "mode": stat.S_IFMT(info.st_mode), "device": info.st_dev,
                            "inode": info.st_ino,
                            "attributes": getattr(info, "st_file_attributes", 0),
                        }
            except FileNotFoundError:
                reasons.append("TARGET_NO_LONGER_EXISTS")
            except PermissionError:
                reasons.append("ACCESS_DENIED")
            except OSError as exc:
                reasons.append(
                    "TARGET_IN_USE" if getattr(exc, "winerror", None) == 32
                    else "TARGET_METADATA_ERROR")
        if fingerprint is not None:
            expected = {
                "size": record["expected_size"],
                "mtime_ns": record["expected_mtime_ns"],
                "ctime_ns": record["expected_ctime_ns"],
                "device": record["expected_device"],
                "inode": record["expected_inode"],
            }
            comparable = dict(fingerprint)
            comparable["device"] = _sqlite_identity(int(comparable["device"]))
            comparable["inode"] = _sqlite_identity(int(comparable["inode"]))
            if any(comparable[key] != value for key, value in expected.items()):
                reasons.append("TARGET_CHANGED_SINCE_CREATE")
        checks.extend([
            {"check": "controlled_probe_registry", "passed": record.get("session_id") == self.session_id},
            {"check": "exact_probe_session_root", "passed": "CONTROLLED_PROBE_BOUNDARY_BLOCKED" not in reasons},
            {"check": "current_filesystem_metadata", "passed": fingerprint is not None},
            {"check": "creation_fingerprint", "passed": fingerprint is not None and "TARGET_CHANGED_SINCE_CREATE" not in reasons},
        ])
        return {
            "probe_id": record.get("probe_id"), "candidate_id": None,
            "current_path": path, "execution_rule_id": PROBE_RULE_VERSION,
            "created_at": record.get("created_at"),
            "snapshot_size": record.get("expected_size"),
            "snapshot_mtime": _iso_from_ns(int(record["expected_mtime_ns"])),
            "current_size": fingerprint["size"] if fingerprint else None,
            "current_mtime": _iso_from_ns(fingerprint["mtime_ns"]) if fingerprint else None,
            "eligibility": "eligible_for_recycle" if not reasons else "ineligible",
            "checks": checks, "block_reasons": list(dict.fromkeys(reasons)),
            "planned_action": "recycle" if not reasons else "none",
            "fingerprint": fingerprint,
        }
