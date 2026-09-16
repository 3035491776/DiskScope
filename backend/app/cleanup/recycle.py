"""Fail-closed Windows Recycle Bin backend for one controlled probe file."""

from __future__ import annotations

import ntpath
import os
from dataclasses import dataclass


class RecycleError(RuntimeError):
    def __init__(self, code: str, hresult: int | None = None):
        self.code = code
        self.hresult = hresult
        super().__init__(code)


@dataclass(frozen=True)
class RecycleResult:
    backend: str
    api_outcome: str
    original_path_absent: bool


def _failed_hresult(value: int) -> bool:
    return value < 0


class WindowsRecycleBackend:
    """Use IFileOperation with FOFX_RECYCLEONDELETE; never fall back to unlink."""

    name = "windows_ifileoperation"

    def recycle(self, path: str) -> RecycleResult:
        if os.name != "nt":
            raise RecycleError("RECYCLE_BACKEND_UNAVAILABLE")
        if (not isinstance(path, str) or not ntpath.isabs(path) or
                ntpath.splitdrive(path)[0].casefold() != "c:" or
                path.startswith(("\\\\", "\\\\?\\", "\\\\.\\"))):
            raise RecycleError("RECYCLE_PATH_BLOCKED")

        # Imports remain local so policy and service tests can run on non-Windows hosts.
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

            @classmethod
            def parse(cls, value: str):
                raw = uuid.UUID(value).bytes_le
                return cls.from_buffer_copy(raw)

        ole32 = ctypes.OleDLL("ole32")
        shell32 = ctypes.OleDLL("shell32")
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p),
        ]
        ole32.CoCreateInstance.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        shell32.SHCreateItemFromParsingName.argtypes = [
            wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        shell32.SHCreateItemFromParsingName.restype = ctypes.c_long

        operation = ctypes.c_void_p()
        item = ctypes.c_void_p()
        initialized = False

        def method(pointer, index, result_type, *argument_types):
            table = ctypes.cast(
                pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            return ctypes.WINFUNCTYPE(
                result_type, ctypes.c_void_p, *argument_types)(table[index])

        def require_ok(result: int, code: str) -> None:
            if _failed_hresult(result):
                hresult = result & 0xFFFFFFFF
                if hresult == 0x80070005:
                    raise RecycleError("ACCESS_DENIED", hresult)
                if hresult in {0x80070020, 0x80070021}:
                    raise RecycleError("TARGET_IN_USE", hresult)
                raise RecycleError(code, hresult)

        try:
            # IFileOperation is supported only from a single-threaded apartment.
            require_ok(ole32.CoInitializeEx(None, 0x2), "RECYCLE_COM_INITIALIZATION_FAILED")
            initialized = True
            clsid_file_operation = GUID.parse("3ad05575-8857-4850-9277-11b85bdb8e09")
            iid_file_operation = GUID.parse("947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8")
            iid_shell_item = GUID.parse("43826d1e-e718-42ee-bc55-a1e261c37bfe")
            require_ok(ole32.CoCreateInstance(
                ctypes.byref(clsid_file_operation), None, 0x1,
                ctypes.byref(iid_file_operation), ctypes.byref(operation)),
                "RECYCLE_COM_CREATE_FAILED")
            require_ok(shell32.SHCreateItemFromParsingName(
                path, None, ctypes.byref(iid_shell_item), ctypes.byref(item)),
                "RECYCLE_SHELL_ITEM_FAILED")

            set_flags = method(operation, 5, ctypes.c_long, wintypes.DWORD)
            delete_item = method(
                operation, 18, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
            perform = method(operation, 21, ctypes.c_long)
            get_aborted = method(
                operation, 22, ctypes.c_long, ctypes.POINTER(wintypes.BOOL))

            # FOFX_RECYCLEONDELETE is the fail-closed semantic. Remaining flags
            # suppress Shell UI and copy hooks; none permits permanent deletion.
            flags = 0x00080000 | 0x00800000 | 0x0040 | 0x0400 | 0x0010 | 0x0004
            require_ok(set_flags(operation, flags), "RECYCLE_SET_FLAGS_FAILED")
            require_ok(delete_item(operation, item, None), "RECYCLE_QUEUE_FAILED")
            perform_result = perform(operation)
            aborted = wintypes.BOOL()
            aborted_result = get_aborted(operation, ctypes.byref(aborted))
            require_ok(aborted_result, "RECYCLE_ABORT_STATUS_FAILED")
            if aborted.value:
                raise RecycleError("RECYCLE_OPERATION_ABORTED")
            require_ok(perform_result, "RECYCLE_OPERATION_FAILED")
            if os.path.lexists(path):
                raise RecycleError("RECYCLE_ORIGINAL_PATH_REMAINS")
            return RecycleResult(self.name, "success", True)
        except RecycleError:
            raise
        except Exception as exc:
            raise RecycleError("RECYCLE_BACKEND_FAILED") from exc
        finally:
            if item.value:
                method(item, 2, wintypes.ULONG)(item)
            if operation.value:
                method(operation, 2, wintypes.ULONG)(operation)
            if initialized:
                ole32.CoUninitialize()
