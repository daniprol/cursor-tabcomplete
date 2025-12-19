#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.27",
#     "protobuf>=4.25",
#     "python-dotenv>=1.0",
# ]
# ///
"""
Minimal StreamCpp client using uv's single-file script support (PEP 723).
Set CURSOR_BEARER_TOKEN, X_REQUEST_ID, X_SESSION_ID, X_CURSOR_CLIENT_VERSION
in your environment or .env. Generate proto stubs into ./proto_gen first.
"""

import argparse
import os
import struct
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
PROTO_DIR = ROOT / "proto_gen"

if not PROTO_DIR.exists():
    raise SystemExit("Missing proto_gen; run the protoc command listed in README first.")

# Make generated modules importable without extra packaging.
sys.path.insert(0, str(PROTO_DIR))
import streamCppRequest_pb2 as req_pb2  # type: ignore  # noqa: E402
import streamCppResponse_pb2 as resp_pb2  # type: ignore  # noqa: E402

load_dotenv()


def frame(message: bytes) -> bytes:
    """Wrap protobuf bytes in Connect envelope: flags(1) + len(4) + body."""
    return b"\x00" + struct.pack(">I", len(message)) + message


def parse_stream(chunks):
    """Yield decoded StreamCppResponse objects and trailers from Connect frames."""
    buffer = b""
    for chunk in chunks:
        buffer += chunk
        while len(buffer) >= 5:
            flags = buffer[0]
            msg_len = struct.unpack(">I", buffer[1:5])[0]
            if len(buffer) < 5 + msg_len:
                break
            msg = buffer[5 : 5 + msg_len]
            buffer = buffer[5 + msg_len :]
            if flags & 0x02:
                yield ("trailer", msg.decode("utf-8", "ignore"))
            else:
                yield ("data", resp_pb2.StreamCppResponse.FromString(msg))
    if buffer:
        yield ("leftover", buffer.hex())


def build_request(
    text: str,
    filename: str,
    language: str,
    cursor_line: int,
    cursor_col: int,
) -> req_pb2.StreamCppRequest:
    now = time.time()
    current_file = req_pb2.CurrentFileInfo(
        relative_workspace_path=filename,
        contents=text,
        cursor_position=req_pb2.CursorPosition(line=cursor_line, column=cursor_col),
        dataframes=[],
        language_id=language,
        diagnostics=[],
        total_number_of_lines=text.count("\n") + 1,
        contents_start_at_line=0,
        top_chunks=[],
        cell_start_lines=[],
        cells=[],
        rely_on_filesync=False,
        workspace_root_path=str(Path.cwd()),
        line_ending="\n",
    )
    return req_pb2.StreamCppRequest(
        current_file=current_file,
        diff_history=[],
        model_name="fast",
        diff_history_keys=[],
        give_debug_output=False,
        file_diff_histories=[
            req_pb2.FileDiffHistory(file_name=filename, diff_history=["1+| \n"])
        ],
        merged_diff_histories=[],
        block_diff_patches=[],
        context_items=[],
        parameter_hints=[],
        lsp_contexts=[],
        cpp_intent_info=req_pb2.CppIntentInfo(source="line_change"),
        workspace_id="",
        additional_files=[],
        client_time=now,
        filesync_updates=[],
        time_since_request_start=now,
        time_at_request_send=now,
        client_timezone_offset=-time.timezone / 60.0,
        lsp_suggested_items=req_pb2.LspSuggestedItems(),
        supports_cpt=False,
        supports_crlf_cpt=False,
        code_results=[],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a Cursor StreamCpp request with the given file text."
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Logical filename sent to Cursor (e.g. app.py).",
    )
    parser.add_argument(
        "--text",
        help="Inline file text. Use --text-file to load from disk instead.",
    )
    parser.add_argument(
        "--text-file",
        help="Path to file whose contents are sent to Cursor.",
    )
    parser.add_argument(
        "--language",
        default="python",
        help="Language id to send (default: python).",
    )
    parser.add_argument(
        "--cursor-line",
        type=int,
        default=0,
        help="Zero-based cursor line.",
    )
    parser.add_argument(
        "--cursor-col",
        type=int,
        default=0,
        help="Zero-based cursor column.",
    )
    parser.add_argument(
        "--debug-frames",
        action="store_true",
        help="Print raw frame info for debugging.",
    )
    args = parser.parse_args()

    if not args.text and not args.text_file:
        raise SystemExit("Provide --text or --text-file.")
    text = (
        Path(args.text_file).read_text(encoding="utf-8")
        if args.text_file
        else args.text
    )
    if text and "\\n" in text and "\n" not in text:
        # Allow literal "\n" in CLI args.
        text = text.encode("utf-8").decode("unicode_escape")

    token = os.getenv("CURSOR_BEARER_TOKEN")
    if not token:
        raise SystemExit("Set CURSOR_BEARER_TOKEN in your environment or .env.")

    request_msg = build_request(
        text=text,
        filename=args.file,
        language=args.language,
        cursor_line=args.cursor_line,
        cursor_col=args.cursor_col,
    )
    if args.debug_frames:
        print(f"[debug] request bytes: {len(request_msg.SerializeToString())}")
        print("[debug] request message:")
        print(request_msg)
    payload = frame(request_msg.SerializeToString())

    headers = {
        "connect-accept-encoding": "gzip",
        "connect-content-encoding": "gzip",
        "connect-protocol-version": "1",
        "content-type": "application/connect+proto",
        "x-cursor-client-type": "ide",
        "x-cursor-client-version": os.getenv("X_CURSOR_CLIENT_VERSION", ""),
        "x-cursor-streaming": "true",
        "x-request-id": os.getenv("X_REQUEST_ID", ""),
        "x-session-id": os.getenv("X_SESSION_ID", ""),
        "authorization": f"Bearer {token}",
        "content-length": str(len(payload)),
    }

    url = "https://us-only.gcpp.cursor.sh/aiserver.v1.AiService/StreamCpp"
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)

    with httpx.Client(http2=False, timeout=timeout) as client:
        with client.stream("POST", url, headers=headers, content=payload) as res:
            res.raise_for_status()
            completion_parts: list[str] = []
            trailer = None
            leftover = None
            for kind, part in parse_stream(res.iter_raw()):
                if kind == "data" and isinstance(part, resp_pb2.StreamCppResponse):
                    if args.debug_frames:
                        print(
                            f"[frame data] text_len={len(part.text)} "
                            f"done_edit={part.done_edit} done_stream={part.done_stream}"
                        )
                    if part.text:
                        completion_parts.append(part.text)
                elif kind == "trailer":
                    trailer = part
                    if args.debug_frames:
                        print(f"[frame trailer] {trailer}")
                elif kind == "leftover":
                    leftover = part
                    if args.debug_frames:
                        print(f"[frame leftover] {leftover}")

    print("".join(completion_parts))
    if trailer:
        print("\n[trailer]\n", trailer)
    if leftover:
        print("\n[leftover bytes]\n", leftover)


if __name__ == "__main__":
    main()
