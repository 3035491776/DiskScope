"""Fixed scope registry; only the C scope can select the C-drive policy."""

from dataclasses import dataclass
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.scanner.c_drive import C_ROOT, SYSTEM_DRIVE_LABEL, SYSTEM_DRIVE_SCOPE_KEY, validate_system_drive_c
from app.scanner.path_guard import InvalidScanRoot, validate_scan_root
from app.scanner.policy import C_DRIVE_SAFE_READONLY, SCAN_POLICY, ScanPolicy


@dataclass(frozen=True)
class ScanScope:
    scope_key: str
    label: str
    root: Path
    policy: ScanPolicy
    whole_volume: bool = False
    snapshot_enabled: bool = True

    @property
    def result_root_label(self) -> str:
        if self.scope_key == "fixture_sample":
            return "tests/fixtures/sample_disk"
        if self.scope_key.startswith("fixture_path:"):
            return self.scope_key.removeprefix("fixture_path:")
        return self.scope_key


FIXED_SCOPES = {
    "fixture_sample": ScanScope("fixture_sample", "Fixture Sample", PROJECT_ROOT / "tests" / "fixtures" / "sample_disk", SCAN_POLICY),
    "project_workspace": ScanScope("project_workspace", "Project Workspace", PROJECT_ROOT, SCAN_POLICY),
    SYSTEM_DRIVE_SCOPE_KEY: ScanScope(SYSTEM_DRIVE_SCOPE_KEY, SYSTEM_DRIVE_LABEL, C_ROOT, C_DRIVE_SAFE_READONLY, True),
}


class CDriveConfirmationRequired(ValueError):
    code = "C_DRIVE_CONFIRMATION_REQUIRED"


def resolve_scan_scope(
    requested_root: str | None = None,
    scope_key: str | None = None,
    confirmed_readonly: bool = False,
) -> ScanScope:
    if scope_key is not None:
        if requested_root is not None:
            raise InvalidScanRoot("Use a fixed scope_key without a root path.")
        definition = FIXED_SCOPES.get(scope_key)
        if definition is None:
            raise InvalidScanRoot("Unknown scan scope.")
        if scope_key == SYSTEM_DRIVE_SCOPE_KEY:
            if not confirmed_readonly:
                raise CDriveConfirmationRequired("C_DRIVE_CONFIRMATION_REQUIRED")
            validate_system_drive_c()
            return definition
        root, _ = validate_scan_root(str(definition.root))
        return ScanScope(definition.scope_key, definition.label, root, definition.policy)
    if requested_root is None:
        raise InvalidScanRoot("A fixed scope or approved root is required.")
    root, root_label = validate_scan_root(requested_root)
    if root_label == "project_workspace":
        return ScanScope("project_workspace", "Project Workspace", root, SCAN_POLICY)
    if root_label == "tests/fixtures/sample_disk":
        return ScanScope("fixture_sample", "Fixture Sample", root, SCAN_POLICY)
    return ScanScope(f"fixture_path:{root_label}", root_label, root, SCAN_POLICY)
