# -*- coding: utf-8 -*-
"""SocialReader 本地 Web 控制台（仅监听 127.0.0.1）。"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
PIPELINE = ROOT / "pipeline_capture.py"
PYTHON = Path(sys.executable)
OUTPUT_ROOT = Path(os.environ.get("SOCIALREADER_OUTPUT_ROOT", r"D:\ObsidianVault\采集\内容流水线")).expanduser()
START_BROWSER = ROOT / "start_browser.bat"
HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEBUG_PORT = 9333
MAX_BODY = 64 * 1024
MAX_LOG_LINES = 1200


def debug_browser_ready() -> bool:
    try:
        with socket.create_connection((HOST, DEBUG_PORT), timeout=0.6):
            return True
    except OSError:
        return False


def file_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "relative": path.relative_to(OUTPUT_ROOT).as_posix(),
        "folder": path.parent.name,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().strftime("%m-%d %H:%M"),
        "is_summary": path.name == "_汇总.md",
    }


def recent_markdown(limit: int = 30) -> list[dict[str, Any]]:
    if not OUTPUT_ROOT.exists():
        return []
    paths = sorted(
        (path for path in OUTPUT_ROOT.rglob("*.md") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [file_record(path) for path in paths[:limit]]


def safe_output_file(relative: str) -> Path:
    root = OUTPUT_ROOT.resolve()
    candidate = (root / relative.replace("/", os.sep)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("文件路径超出采集目录") from exc
    if candidate.suffix.lower() != ".md" or not candidate.is_file():
        raise FileNotFoundError("Markdown 文件不存在")
    return candidate


class JobManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.process: subprocess.Popen[str] | None = None
        self.job: dict[str, Any] = self._idle_job()

    @staticmethod
    def _idle_job() -> dict[str, Any]:
        return {
            "id": "",
            "state": "idle",
            "platform": "",
            "query": "",
            "maximum": 0,
            "model": "small",
            "current": 0,
            "total": 0,
            "success": 0,
            "failed": 0,
            "started_at": "",
            "finished_at": "",
            "message": "等待开始",
            "logs": [],
            "exit_code": None,
        }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            data = dict(self.job)
            data["logs"] = list(self.job["logs"])
            data["running"] = self.process is not None and self.process.poll() is None
            data["can_confirm"] = data["running"] and data["state"] == "awaiting_login"
            return data

    def start(self, platform: str, query: str, maximum: int, model: str) -> dict[str, Any]:
        if platform not in {"xhs", "dy", "dyvideo"}:
            raise ValueError("平台参数无效")
        query = query.strip()
        if not query:
            raise ValueError("请输入关键词或抖音链接")
        if len(query) > 300:
            raise ValueError("输入内容过长")
        if not 1 <= maximum <= 20:
            raise ValueError("采集数量必须在 1–20 之间")
        if model not in {"tiny", "base", "small", "medium"}:
            raise ValueError("转写模型无效")
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise RuntimeError("已有任务正在运行，请等待完成或先停止")
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            env["PYTHONUTF8"] = "1"
            command = [
                str(PYTHON),
                "-u",
                str(PIPELINE),
                platform,
                query,
                "--max",
                str(maximum),
                "--asr-model",
                model,
            ]
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            self.process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            self.job = {
                **self._idle_job(),
                "id": uuid.uuid4().hex,
                "state": "starting",
                "platform": platform,
                "query": query,
                "maximum": maximum,
                "model": model,
                "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "message": "正在连接调试浏览器…",
            }
            process = self.process
            job_id = self.job["id"]
        threading.Thread(target=self._read_output, args=(process, job_id), daemon=True).start()
        return self.snapshot()

    def _append_log(self, line: str) -> None:
        line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).rstrip()
        if not line:
            return
        self.job["logs"].append(line)
        if len(self.job["logs"]) > MAX_LOG_LINES:
            self.job["logs"] = self.job["logs"][-MAX_LOG_LINES:]
        if "请在调试浏览器窗口中扫码/登录" in line:
            self.job["state"] = "awaiting_login"
            self.job["message"] = "请在调试浏览器完成登录，然后点击“我已登录，继续”"
        elif line.startswith("== 小红书 搜索") or line.startswith("== 抖音 搜索"):
            self.job["state"] = "running"
            self.job["message"] = "正在搜索并整理内容链接…"
        elif line.startswith("["):
            progress = re.match(r"\[(\d+)/(\d+)\]", line)
            if progress:
                self.job["state"] = "running"
                self.job["current"] = int(progress.group(1))
                self.job["total"] = int(progress.group(2))
                self.job["message"] = f"正在处理第 {progress.group(1)} / {progress.group(2)} 条"
        if "[视频] 已下载" in line:
            self.job["message"] = "视频已下载，正在语音转写…"
        elif "[图文] 已保存" in line:
            self.job["message"] = "图文图片已保存，正在写入 Markdown…"
        elif "[转写] 成功" in line:
            self.job["message"] = "视频转写成功，正在保存…"
        elif "完成：成功" in line:
            result = re.search(r"成功\s+(\d+)\s+篇\s+/\s+失败\s+(\d+)\s+条", line)
            if result:
                self.job["success"] = int(result.group(1))
                self.job["failed"] = int(result.group(2))

    def _read_output(self, process: subprocess.Popen[str], job_id: str) -> None:
        try:
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    with self.lock:
                        if self.job["id"] != job_id:
                            break
                        self._append_log(line)
            code = process.wait()
        except Exception as exc:
            code = 1
            with self.lock:
                if self.job["id"] == job_id:
                    self._append_log(f"[Web 控制台异常] {type(exc).__name__}: {exc}")
        with self.lock:
            if self.job["id"] != job_id:
                return
            self.job["exit_code"] = code
            self.job["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            if self.job["state"] == "stopping":
                self.job["state"] = "stopped"
                self.job["message"] = "任务已停止"
            elif code == 0:
                self.job["state"] = "done"
                self.job["message"] = f"采集完成：成功 {self.job['success']} 篇，失败 {self.job['failed']} 条"
            else:
                self.job["state"] = "failed"
                if self.job["state"] != "awaiting_login":
                    self.job["message"] = f"任务未完成（退出码 {code}），请查看日志"
            self.process = None

    def confirm_login(self) -> dict[str, Any]:
        with self.lock:
            if not self.process or self.process.poll() is not None:
                raise RuntimeError("当前没有等待登录的任务")
            if self.job["state"] != "awaiting_login":
                raise RuntimeError("任务当前不在登录确认阶段")
            if not self.process.stdin:
                raise RuntimeError("无法向采集进程发送确认")
            self.process.stdin.write("\n")
            self.process.stdin.flush()
            self.job["state"] = "running"
            self.job["message"] = "登录已确认，正在开始采集…"
            self._append_log("[Web 控制台] 已确认登录，继续执行")
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        with self.lock:
            process = self.process
            if not process or process.poll() is not None:
                raise RuntimeError("当前没有运行中的任务")
            self.job["state"] = "stopping"
            self.job["message"] = "正在停止任务…"
            pid = process.pid
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                process.terminate()
        except Exception:
            process.terminate()
        return self.snapshot()


JOBS = JobManager()


class SocialReaderHandler(BaseHTTPRequestHandler):
    server_version = "SocialReaderWeb/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stdout.write(f"[Web] {self.address_string()} - {format % args}\n")

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效") from exc
        if length < 0 or length > MAX_BODY:
            raise ValueError("请求内容过大")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("请求必须是 JSON 对象")
        return value

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin", "")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == self.server.server_port

    def _serve_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if parsed.path == "/":
            self._serve_file(WEB_ROOT / "index.html")
            return
        if parsed.path == "/api/status":
            self._json({"ok": True, "browser_ready": debug_browser_ready(), "job": JOBS.snapshot()})
            return
        if parsed.path == "/api/files":
            self._json({"ok": True, "files": recent_markdown()})
            return
        if parsed.path == "/api/file":
            relative = parse_qs(parsed.query).get("relative", [""])[0]
            try:
                path = safe_output_file(relative)
                self._json({"ok": True, "file": file_record(path), "content": path.read_text(encoding="utf-8", errors="replace")})
            except (ValueError, FileNotFoundError) as exc:
                self._error(str(exc), 404)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self._same_origin():
            self._error("来源校验失败", 403)
            return
        try:
            payload = self._read_json()
            if self.path == "/api/start":
                job = JOBS.start(
                    str(payload.get("platform", "")),
                    str(payload.get("query", "")),
                    int(payload.get("maximum", 3)),
                    str(payload.get("model", "small")),
                )
                self._json({"ok": True, "job": job})
                return
            if self.path == "/api/confirm-login":
                self._json({"ok": True, "job": JOBS.confirm_login()})
                return
            if self.path == "/api/stop":
                self._json({"ok": True, "job": JOBS.stop()})
                return
            if self.path == "/api/start-browser":
                if debug_browser_ready():
                    self._json({"ok": True, "message": "调试浏览器已经启动"})
                    return
                os.startfile(str(START_BROWSER))
                self._json({"ok": True, "message": "已启动调试浏览器，请等待 Chrome 打开"})
                return
            if self.path == "/api/open-output":
                OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
                os.startfile(str(OUTPUT_ROOT))
                self._json({"ok": True})
                return
            self._error("接口不存在", 404)
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(str(exc), 400)
        except RuntimeError as exc:
            self._error(str(exc), 409)
        except Exception as exc:
            self._error(f"{type(exc).__name__}: {exc}", 500)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SocialReader 本地 Web 控制台")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"本地端口，默认 {DEFAULT_PORT}")
    parser.add_argument("--no-open", action="store_true", help="启动后不自动打开浏览器")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1024 <= args.port <= 65535:
        print("端口必须在 1024–65535 之间")
        return 2
    if not PIPELINE.exists() or not (WEB_ROOT / "index.html").exists():
        print("[启动失败] pipeline_capture.py 或 web/index.html 不存在")
        return 1
    try:
        server = ThreadingHTTPServer((HOST, args.port), SocialReaderHandler)
    except OSError as exc:
        print(f"[启动失败] 无法监听 {HOST}:{args.port}：{exc}")
        return 1
    url = f"http://{HOST}:{args.port}"
    print("=" * 62)
    print("SocialReader Web 控制台已启动")
    print(f"本地网址：{url}")
    print("关闭本窗口即可停止 Web 控制台")
    print("=" * 62)
    if not args.no_open:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("\nWeb 控制台已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
