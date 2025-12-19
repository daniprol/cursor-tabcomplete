import argparse
from pathlib import Path

from dotenv import dotenv_values
from mitmproxy import io
from mitmproxy.exceptions import FlowReadException


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Cursor StreamCpp headers from a mitmdump flow file and write .env"
    )
    parser.add_argument(
        "--flows",
        required=True,
        help="Path to mitmdump flow file (e.g., .cursor-capture/cursor.flows)",
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="Path to write .env (default: .env)",
    )
    args = parser.parse_args()

    flow_path = Path(args.flows)
    if not flow_path.exists():
        raise SystemExit(f"Flow file not found: {flow_path}")

    latest = None
    with flow_path.open("rb") as fp:
        reader = io.FlowReader(fp)
        try:
            for flow in reader.stream():
                if flow.request and "/StreamCpp" in flow.request.path:
                    latest = flow
        except FlowReadException as e:
            raise SystemExit(f"Failed to read flows: {e}")

    if not latest:
        raise SystemExit("No StreamCpp request found in flows.")

    headers = {k.lower(): v for k, v in latest.request.headers.items()}
    auth = headers.get("authorization", "")
    x_request_id = headers.get("x-request-id", "")
    x_session_id = headers.get("x-session-id", "")
    x_client_version = headers.get("x-cursor-client-version", "")

    missing = [
        name
        for name, val in [
            ("authorization", auth),
            ("x-request-id", x_request_id),
            ("x-session-id", x_session_id),
            ("x-cursor-client-version", x_client_version),
        ]
        if not val
    ]
    if missing:
        raise SystemExit(f"Missing headers in latest StreamCpp flow: {missing}")

    bearer = auth.replace("Bearer", "").strip()

    current = dotenv_values(args.env)
    current.update(
        {
            "CURSOR_BEARER_TOKEN": bearer,
            "X_REQUEST_ID": x_request_id,
            "X_SESSION_ID": x_session_id,
            "X_CURSOR_CLIENT_VERSION": x_client_version,
        }
    )

    lines = [f"{k}={v}" for k, v in current.items()]
    Path(args.env).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.env} with Cursor headers.")


if __name__ == "__main__":
    main()
