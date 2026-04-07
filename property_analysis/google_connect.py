from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


def _repo_data() -> Path:
    p = Path(__file__).resolve().parent.parent / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def token_path() -> Path:
    return _repo_data() / "google_oauth_token.json"


def load_client_config() -> Optional[Dict[str, Any]]:
    raw = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS_JSON", "").strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    try:
        import streamlit as st

        sec = st.secrets.get("GOOGLE_OAUTH_CLIENT_SECRETS_JSON")
        if sec:
            if isinstance(sec, str) and Path(sec).expanduser().is_file():
                return json.loads(Path(sec).expanduser().read_text(encoding="utf-8"))
            if isinstance(sec, dict):
                return dict(sec)
    except Exception:
        pass
    return None


def redirect_uri_default() -> str:
    u = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    if u:
        return u
    try:
        import streamlit as st

        x = st.secrets.get("GOOGLE_OAUTH_REDIRECT_URI")
        if x:
            return str(x).strip()
    except Exception:
        pass
    return "http://localhost:8501/"


def spreadsheet_id_config() -> str:
    v = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if v:
        return v
    try:
        import streamlit as st

        x = st.secrets.get("GOOGLE_SHEET_ID")
        if x:
            return str(x).strip()
    except Exception:
        pass
    return ""


def save_token(creds: Any) -> None:
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }
    token_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_saved_credentials():
    from google.oauth2.credentials import Credentials

    p = token_path()
    if not p.is_file():
        return None
    try:
        return Credentials.from_authorized_user_file(str(p), scopes=_SCOPES)
    except Exception:
        return None


def build_flow(client_config: Dict[str, Any], redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        client_config,
        scopes=_SCOPES,
        redirect_uri=redirect_uri,
    )


def authorization_url_and_state(client_config: Dict[str, Any], redirect_uri: str) -> tuple[str, str]:
    flow = build_flow(client_config, redirect_uri)
    state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return auth_url, state


def exchange_code(client_config: Dict[str, Any], redirect_uri: str, code: str) -> Any:
    flow = build_flow(client_config, redirect_uri)
    flow.fetch_token(code=code)
    return flow.credentials


def push_rows_with_user_creds(
    creds: Any,
    spreadsheet_id: Optional[str],
    worksheet_title: str,
    headers: List[str],
    rows: List[List[Any]],
) -> str:
    import gspread

    gc = gspread.authorize(creds)
    sid = (spreadsheet_id or "").strip()
    if sid:
        try:
            sh = gc.open_by_key(sid)
        except Exception:
            sh = gc.create("Property Portfolio")
            sid = sh.id
    else:
        sh = gc.create("Property Portfolio")
        sid = sh.id
    try:
        ws = sh.worksheet(worksheet_title)
    except Exception:
        ws = sh.add_worksheet(title=worksheet_title, rows=500, cols=max(26, len(headers) + 2))
    body = [headers] + rows
    ws.clear()
    ws.update(body, value_input_option="USER_ENTERED")
    return sid


def install_google_packages() -> None:
    import subprocess
    import sys

    pkgs = [
        "gspread>=5.0",
        "google-auth>=2.0",
        "google-auth-oauthlib>=1.0",
        "google-auth-httplib2>=0.2",
        "google-api-python-client>=2.0",
    ]
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *pkgs], timeout=300)
