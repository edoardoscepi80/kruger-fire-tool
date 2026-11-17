"""
Online Auto-Update Module for Kruger Fire & Rainfall Management DSS
Supports checking remote/local version manifests, downloading update packages (.zip or .exe),
and safely applying updates.
"""

import os
import re
import sys
import json
import shutil
import zipfile
import hashlib
import tempfile
import subprocess
import urllib.request
from typing import Tuple, Dict, Any, Optional

from PyQt5.QtCore import QThread, pyqtSignal


def parse_version(v_str: str) -> Tuple[int, ...]:
    """Parse a version string (e.g. '1.2.3' or 'v1.0.4b') into a comparable tuple of ints."""
    clean = re.sub(r'^[vV]', '', str(v_str).strip())
    parts = []
    for segment in clean.split('.'):
        match = re.match(r'(\d+)', segment)
        if match:
            parts.append(int(match.group(1)))
        else:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def fetch_manifest(manifest_url: str) -> Dict[str, Any]:
    """Fetch and parse update manifest from HTTP/HTTPS URL or local file path."""
    manifest_url = manifest_url.strip()
    if not manifest_url:
        raise ValueError("Update manifest URL is empty.")

    if manifest_url.startswith("http://") or manifest_url.startswith("https://"):
        req = urllib.request.Request(
            manifest_url,
            headers={"User-Agent": "Kruger-Fire-DSS-Updater/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = response.read().decode("utf-8")
            return json.loads(data)
    else:
        # Local file path or LAN share
        file_path = manifest_url
        if file_path.startswith("file:///"):
            file_path = file_path[8:]
        elif file_path.startswith("file://"):
            file_path = file_path[7:]
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Update manifest file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)


class CheckUpdateWorker(QThread):
    """Background worker to check for updates without freezing the GUI."""
    updateFound = pyqtSignal(dict)      # Emits update details dictionary
    upToDate = pyqtSignal(str)          # Emits current version
    checkFailed = pyqtSignal(str)       # Emits error message

    def __init__(self, manifest_url: str, current_version: str):
        super().__init__()
        self.manifest_url = manifest_url
        self.current_version = current_version

    def run(self):
        try:
            info = fetch_manifest(self.manifest_url)
            latest_ver = str(info.get("latest_version", "0.0.0")).strip()
            
            cur_tuple = parse_version(self.current_version)
            latest_tuple = parse_version(latest_ver)

            if latest_tuple > cur_tuple:
                info["current_version"] = self.current_version
                self.updateFound.emit(info)
            else:
                self.upToDate.emit(self.current_version)
        except Exception as e:
            self.checkFailed.emit(str(e))


class DownloadUpdateWorker(QThread):
    """Background worker to download update packages with real-time progress."""
    progress = pyqtSignal(int, int, int)       # percentage, bytes_read, total_bytes
    finished = pyqtSignal(str, str, dict)      # downloaded_file_path, package_type, info
    error = pyqtSignal(str)

    def __init__(self, update_info: dict, download_dir: Optional[str] = None):
        super().__init__()
        self.update_info = update_info
        self.download_dir = download_dir or tempfile.gettempdir()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            url = self.update_info.get("download_url", "").strip()
            pkg_type = self.update_info.get("package_type", "archive").lower()
            sha256_expected = self.update_info.get("sha256", "").strip().lower()

            if not url:
                raise ValueError("Update download URL is missing from manifest.")

            # Determine local destination filename
            filename = os.path.basename(url.split("?")[0])
            if not filename:
                ext = ".exe" if pkg_type == "installer" else ".zip"
                filename = f"kruger_update_{self.update_info.get('latest_version', 'latest')}{ext}"

            dest_path = os.path.join(self.download_dir, filename)

            # Download either from web or copy if local path
            if url.startswith("http://") or url.startswith("https://"):
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Kruger-Fire-DSS-Updater/1.0"}
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    total_size = int(response.headers.get("content-length", 0))
                    downloaded = 0
                    chunk_size = 64 * 1024
                    hasher = hashlib.sha256() if sha256_expected else None

                    with open(dest_path, "wb") as f_out:
                        while True:
                            if self._cancelled:
                                return
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            f_out.write(chunk)
                            if hasher:
                                hasher.update(chunk)
                            downloaded += len(chunk)

                            pct = int((downloaded / total_size) * 100) if total_size > 0 else 50
                            self.progress.emit(pct, downloaded, total_size)

                    if sha256_expected and hasher:
                        calc_hash = hasher.hexdigest().lower()
                        if calc_hash != sha256_expected:
                            raise ValueError(
                                f"Integrity check failed! Expected SHA256 {sha256_expected}, but got {calc_hash}."
                            )
            else:
                # Local file copy
                src_path = url
                if src_path.startswith("file:///"):
                    src_path = src_path[8:]
                elif src_path.startswith("file://"):
                    src_path = src_path[7:]

                if not os.path.exists(src_path):
                    raise FileNotFoundError(f"Source update package not found: {src_path}")

                total_size = os.path.getsize(src_path)
                if os.path.abspath(src_path) != os.path.abspath(dest_path):
                    shutil.copyfile(src_path, dest_path)
                self.progress.emit(100, total_size, total_size)

            self.finished.emit(dest_path, pkg_type, self.update_info)

        except Exception as e:
            self.error.emit(str(e))


def launch_installer(installer_path: str, silent: bool = False) -> None:
    """Launch an external .exe installer and prepare to close the application."""
    if not os.path.exists(installer_path):
        raise FileNotFoundError(f"Installer not found: {installer_path}")

    args = [installer_path]
    if silent:
        args.append("/SILENT")

    subprocess.Popen(args, shell=True)


def create_batch_updater_script(zip_path: str, target_dir: str, python_launcher: str, main_script: str) -> str:
    """
    Create a standalone Windows batch script that waits for current app to exit,
    extracts the update ZIP archive over the target directory, and restarts the app.
    """
    batch_path = os.path.join(tempfile.gettempdir(), "apply_kruger_update.bat")
    
    script_content = f"""@echo off
echo =======================================================
echo Updating Kruger Fire ^& Rainfall Management DSS...
echo =======================================================
timeout /t 2 /nobreak > nul

echo Extracting update archive...
powershell -Command "Expand-Archive -Path '{zip_path}' -DestinationPath '{target_dir}' -Force"

if %ERRORLEVEL% NEQ 0 (
    echo Error during update extraction!
    pause
    exit /b 1
)

echo Update successfully applied!
echo Restarting application...
start "" "{python_launcher}" "{main_script}"
exit
"""
    with open(batch_path, "w", encoding="utf-8") as f:
        f.write(script_content)

    return batch_path
