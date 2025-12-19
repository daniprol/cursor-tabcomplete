# Python Cursor StreamCpp Client

Python port of the JS Cursor Unchained StreamCpp client. Uses `uv` + PEP 723 single-file scripts.

## Requirements

- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- mitmdump (optional, for capturing headers): `uv tool install mitmproxy`
- Protobuf compiler via `grpcio-tools` (pulled on demand by `uv run --with grpcio-tools`)

## Setup

Quick manual header grab from Cursor:

1. `cp .env.example .env`
2. Open Cursor.
3. Cmd+Shift+P → “Developer: Open Developer Tools for Extension Host” (pick LocalProcess).
4. Network tab.
5. Trigger a tab completion; find the `StreamCpp` request.
6. Copy headers: `Authorization` (Bearer), `x-request-id`, `x-session-id`, `x-cursor-client-version`.
7. Paste them into `.env`

Generate stubs (once, after cloning):

```bash
mkdir proto_gen
uv run --with grpcio-tools -m grpc_tools.protoc -I protobuf --python_out=proto_gen \
  protobuf/streamCppRequest.proto protobuf/streamCppResponse.proto
```

## Run the StreamCpp client

```bash
uv run stream_cpp.py --file quicksort.py --text-file ./quicksort.py --cursor-line 4 --cursor-col 4
# Inline text example:
uv run stream_cpp.py --file app.py --text "print('hi')\n" --cursor-line 0 --cursor-col 0
```

Env required (via `.env`): `CURSOR_BEARER_TOKEN`, `X_REQUEST_ID`, `X_SESSION_ID`, `X_CURSOR_CLIENT_VERSION`.

## Capture headers automatically (optional)

1. Start proxy capture:

```bash
mitmdump -w .cursor-capture/cursor.flows
```

2. Launch Cursor through the proxy (Fedora example):

```bash
export HTTPS_PROXY=http://127.0.0.1:8080
export NODE_EXTRA_CA_CERTS=$HOME/.mitmproxy/mitmproxy-ca-cert.pem
export ELECTRON_EXTRA_LAUNCH_ARGS="--proxy-server=http=127.0.0.1:8080;https=127.0.0.1:8080 --proxy-bypass-list="
unset NO_PROXY no_proxy
cursor &  # start from this shell
```

3. Trigger a tab completion in Cursor, then extract headers:

```bash
uv run --with mitmproxy --with python-dotenv --with "pyyaml>=6" \
  python scripts/extract_cursor_headers.py --flows .cursor-capture/cursor.flows --env .env
```

Verify Cursor picked up env (optional):

```bash
pgrep -f Cursor | head -1 | xargs -I{} sh -c 'tr "\0" "\n" < /proc/{}/environ | grep -E "HTTPS_PROXY|NODE_EXTRA_CA_CERTS|ELECTRON_EXTRA_LAUNCH_ARGS"'
```

## Fedora trust (MITM CA)

```bash
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /etc/pki/ca-trust/source/anchors/mitmproxy-ca-cert.pem
sudo update-ca-trust
# NSS (Electron/Chromium)
mkdir -p ~/.pki/nssdb
certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n mitmproxy -i ~/.mitmproxy/mitmproxy-ca-cert.pem
```

Remove CA:

```bash
sudo rm /etc/pki/ca-trust/source/anchors/mitmproxy-ca-cert.pem
sudo update-ca-trust
certutil -d sql:$HOME/.pki/nssdb -D -n mitmproxy 2>/dev/null || true
```

## Disclaimer

- This is a Python adaptation of the original JS Cursor Unchained client. Behavior depends on Cursor’s private APIs, which may change or be subject to service terms. Use responsibly and keep tokens private.
