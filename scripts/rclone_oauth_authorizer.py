#!/usr/bin/env python3
"""Generate a Drive-only OAuth token compatible with rclone."""

import argparse
import json
import os
import tempfile
from datetime import timezone
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-secrets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(args.client_secrets), [DRIVE_SCOPE]
    )
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not credentials.refresh_token:
        raise RuntimeError("Google did not return a refresh_token")

    expiry = credentials.expiry
    if expiry is not None:
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        expiry = expiry.astimezone(timezone.utc).replace(microsecond=0)

    token = {
        "access_token": credentials.token or "",
        "token_type": "Bearer",
        "refresh_token": credentials.refresh_token,
    }
    if expiry is not None:
        token["expiry"] = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")
    atomic_json(args.output, token)
    print(f"Token saved atomically to {args.output}")


if __name__ == "__main__":
    main()
