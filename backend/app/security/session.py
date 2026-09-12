import os
import secrets
import threading
import time

from fastapi import HTTPException, Request, Response

from app.core.config import HOST, PORT


COOKIE_NAME = "diskscope_session"
LOCAL_ORIGIN = f"http://{HOST}:{PORT}"
DEV_ORIGIN = f"http://{HOST}:5173"


class LocalSession:
    def __init__(self) -> None:
        self.bootstrap_token = os.environ.get("DISKSCOPE_BOOTSTRAP_TOKEN") or secrets.token_urlsafe(32)
        self.bootstrap_expires_at = time.monotonic() + 120
        self.session_token = secrets.token_urlsafe(32)
        self._used = False
        self._lock = threading.Lock()

    def exchange(self, supplied_token: str, response: Response) -> None:
        with self._lock:
            if (
                self._used
                or time.monotonic() > self.bootstrap_expires_at
                or not secrets.compare_digest(supplied_token, self.bootstrap_token)
            ):
                raise HTTPException(status_code=401, detail="Invalid or expired launch token.")
            self._used = True
        response.set_cookie(
            COOKIE_NAME,
            self.session_token,
            httponly=True,
            samesite="strict",
            path="/api/v1",
        )


local_session = LocalSession()


def require_local_origin(request: Request) -> None:
    allowed = {LOCAL_ORIGIN}
    if os.environ.get("DISKSCOPE_DEV_MODE") == "1":
        allowed.add(DEV_ORIGIN)
    if request.headers.get("origin") not in allowed:
        raise HTTPException(status_code=403, detail="Invalid request origin.")


def require_session(request: Request) -> None:
    supplied = request.cookies.get(COOKIE_NAME, "")
    if not supplied or not secrets.compare_digest(supplied, local_session.session_token):
        raise HTTPException(status_code=401, detail="A local session is required.")
