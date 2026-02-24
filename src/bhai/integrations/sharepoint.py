"""
SharePoint integration via Microsoft Graph API.
Uses MSAL device code flow for authentication (no client secret needed).
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import msal
import requests

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Files.ReadWrite.All", "Sites.Read.All"]

# Only ever write to this worksheet — safety guard
_TARGET_WORKSHEET = "Live_Transcription_Sundar"

TOKEN_CACHE_PATH = Path.home() / ".bhai_token_cache.json"


class SharePointClient:
    """Client for SharePoint operations via Microsoft Graph API."""

    def __init__(self, tenant_id: str, client_id: str, hostname: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.hostname = hostname
        self._token: Optional[str] = None
        self._site_id: Optional[str] = None
        self._drive_id: Optional[str] = None

        # Set up MSAL with persistent token cache
        self._cache = msal.SerializableTokenCache()
        if TOKEN_CACHE_PATH.exists():
            self._cache.deserialize(TOKEN_CACHE_PATH.read_text())

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        self._app = msal.PublicClientApplication(
            client_id,
            authority=authority,
            token_cache=self._cache,
        )

    def _save_cache(self) -> None:
        if self._cache.has_state_changed:
            TOKEN_CACHE_PATH.write_text(self._cache.serialize())

    def authenticate(self) -> str:
        """Authenticate via device code flow. Returns access token."""
        # Try cached token first
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._token = result["access_token"]
                self._save_cache()
                return self._token

        # Fall back to device code flow
        flow = self._app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Device flow failed: {flow.get('error_description', flow)}")

        print(f"\n{'='*60}", flush=True)
        print(f"To sign in, open: {flow['verification_uri']}", flush=True)
        print(f"Enter code: {flow['user_code']}", flush=True)
        print(f"{'='*60}\n", flush=True)

        result = self._app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"Auth failed: {result.get('error_description', result)}")

        self._token = result["access_token"]
        self._save_cache()
        return self._token

    def _headers(self) -> dict[str, str]:
        if not self._token:
            self.authenticate()
        return {"Authorization": f"Bearer {self._token}"}

    def _refresh_and_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a request, auto-refreshing the token on 401."""
        resp = requests.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code == 401:
            logger.info("Token expired, re-authenticating...")
            self._token = None
            self.authenticate()
            resp = requests.request(method, url, headers=self._headers(), **kwargs)
        return resp

    def _get(self, url: str, params: Optional[dict] = None) -> dict:
        resp = self._refresh_and_retry("GET", url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, url: str, json_body: Any) -> dict:
        resp = self._refresh_and_retry("POST", url, json=json_body)
        resp.raise_for_status()
        return resp.json()

    # ── Site & Drive discovery ──────────────────────────────────

    def get_site_id(self) -> str:
        """Get the root site ID for the SharePoint hostname."""
        if self._site_id:
            return self._site_id
        data = self._get(f"{GRAPH_BASE}/sites/{self.hostname}")
        self._site_id = data["id"]
        logger.info("Site ID: %s", self._site_id)
        return self._site_id

    def get_drive_id(self, drive_name: Optional[str] = None) -> str:
        """Get the document library drive ID. If drive_name is None, returns default drive."""
        if self._drive_id:
            return self._drive_id

        site_id = self.get_site_id()
        if drive_name:
            # List all drives and find by name
            data = self._get(f"{GRAPH_BASE}/sites/{site_id}/drives")
            for drive in data["value"]:
                if drive["name"] == drive_name:
                    self._drive_id = drive["id"]
                    break
            if not self._drive_id:
                available = [d["name"] for d in data["value"]]
                raise ValueError(f"Drive '{drive_name}' not found. Available: {available}")
        else:
            data = self._get(f"{GRAPH_BASE}/sites/{site_id}/drive")
            self._drive_id = data["id"]

        logger.info("Drive ID: %s", self._drive_id)
        return self._drive_id

    # ── File operations ─────────────────────────────────────────

    def list_drives(self) -> list[dict]:
        """List all document libraries (drives) on the site."""
        site_id = self.get_site_id()
        data = self._get(f"{GRAPH_BASE}/sites/{site_id}/drives")
        return data["value"]

    def list_folder_children(self, folder_path: str) -> list[dict]:
        """List items in a folder by path (relative to drive root)."""
        drive_id = self.get_drive_id()
        url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{folder_path}:/children"
        items = []
        while url:
            data = self._get(url)
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return items

    def list_audio_files(self, folder_path: str) -> list[dict]:
        """List only audio files in a folder (by extension)."""
        audio_exts = {".ogg", ".wav", ".mp3", ".m4a", ".opus"}
        items = self.list_folder_children(folder_path)
        return [
            item for item in items
            if not item.get("folder")
            and Path(item["name"]).suffix.lower() in audio_exts
        ]

    def download_file(self, file_id: str, local_path: Path) -> Path:
        """Download a file by its ID to a local path."""
        drive_id = self.get_drive_id()
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{file_id}/content"
        resp = self._refresh_and_retry("GET", url, allow_redirects=True)
        resp.raise_for_status()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(resp.content)
        return local_path

    # ── Excel operations (scoped to Live_Transcription_Sundar) ──

    def _get_workbook_item_id(self, file_path: str) -> str:
        """Get the item ID of an Excel file by its path in the drive."""
        drive_id = self.get_drive_id()
        data = self._get(f"{GRAPH_BASE}/drives/{drive_id}/root:/{file_path}")
        return data["id"]

    def append_excel_rows(
        self,
        workbook_path: str,
        rows: list[list[str]],
    ) -> dict:
        """
        Append rows to the Live_Transcription_Sundar worksheet.

        SAFETY: worksheet name is hardcoded — never parameterized.

        Args:
            workbook_path: Path to the Excel file in the drive (e.g. "Voice2Voice/Voice2Voice Final - Tracker.xlsx")
            rows: List of rows, each row is a list of cell values
        """
        drive_id = self.get_drive_id()
        item_id = self._get_workbook_item_id(workbook_path)

        # Get the used range to find the next empty row
        worksheet = quote(_TARGET_WORKSHEET, safe="")
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/workbook/worksheets/{worksheet}/usedRange"
        try:
            used_range = self._get(url)
            # usedRange address looks like "Live_Transcription_Sundar!A1:F50"
            last_row = len(used_range.get("values", []))
        except requests.HTTPError:
            # Sheet might be empty
            last_row = 0

        if last_row == 0:
            start_row = 1
        else:
            start_row = last_row + 1

        # Build the range address for the new rows
        num_cols = len(rows[0]) if rows else 0
        if num_cols == 0:
            return {}

        end_col = chr(ord("A") + num_cols - 1)
        end_row = start_row + len(rows) - 1
        range_addr = f"A{start_row}:{end_col}{end_row}"

        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/workbook/worksheets/{worksheet}/range(address='{range_addr}')"
        body = {"values": rows}
        resp = self._refresh_and_retry("PATCH", url, json=body)
        resp.raise_for_status()
        logger.info("Appended %d rows to %s!%s", len(rows), worksheet, range_addr)
        return resp.json()

    def read_excel_worksheet_values(
        self,
        workbook_path: str,
    ) -> list[list]:
        """
        Read all values from the Live_Transcription_Sundar worksheet.

        SAFETY: worksheet name is hardcoded.
        """
        drive_id = self.get_drive_id()
        item_id = self._get_workbook_item_id(workbook_path)
        worksheet = quote(_TARGET_WORKSHEET, safe="")
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/workbook/worksheets/{worksheet}/usedRange"
        try:
            data = self._get(url)
            return data.get("values", [])
        except requests.HTTPError:
            return []
