#!/usr/bin/env python3
"""A loopback-only local web app for assembling video sheet music."""
import argparse
import concurrent.futures
import json
import mimetypes
import os
import re
import threading
import time
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from score import compose, extract
from sources import MAX_BYTES, describe_error, download, preview, probe

ROOT = Path(__file__).resolve().parent
DATA = ROOT / ".runtime"
JOBS = {}
LOCK = threading.RLock()
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=1)


class Cancelled(Exception):
    pass


def public(job):
    return {key: value for key, value in job.items() if key not in ("cancel", "path")}


def update(job, **kwargs):
    with LOCK:
        job.update(kwargs)


def checkpoint(job):
    if job["cancel"].is_set():
        raise Cancelled()


def new_job(title):
    key = uuid.uuid4().hex
    folder = DATA / key
    folder.mkdir(parents=True)
    job = {"id": key, "title": title, "state": "queued", "progress": 0,
           "message": "等待处理", "cancel": threading.Event(), "created": time.time(),
           "path": str(folder), "result": None}
    with LOCK:
        JOBS[key] = job
    return job


def run(job, operation):
    try:
        checkpoint(job)
        operation()
    except Cancelled:
        update(job, state="cancelled", message="已取消，可以重新选择视频。")
    except Exception as exc:
        # Paths, media CDN signatures and tracebacks stay out of the browser UI.
        message = describe_error(exc)
        update(job, state="error", message=message)
        print(f"Job {job['id']}: {type(exc).__name__}: {exc}", flush=True)


def prepare(job, link=None):
    folder = Path(job["path"])
    update(job, state="preparing", message="读取视频")
    if link:
        source, metadata = download(link, folder,
                                    lambda n, m: update(job, progress=n, message=m),
                                    lambda: checkpoint(job))
    else:
        source = folder / "source.mp4"
        metadata = {"title": job["title"], "author": "本地上传", "source": ""}
    checkpoint(job)
    metadata["video"] = probe(source)
    preview(source, folder / "preview.jpg")
    checkpoint(job)
    update(job, **metadata, state="ready", progress=100, message="视频已就绪，请确认谱面区域。")


def process_job(job, options):
    folder = Path(job["path"])
    update(job, state="processing", progress=0, message="开始扫描视频")
    metadata = {key: job[key] for key in ("title", "author", "source", "video")}
    title = str(options.get("title", "")).strip()
    if title:
        metadata["title"] = title[:120]
    (folder / "header.png").unlink(missing_ok=True)
    result = extract(folder / "source.mp4", folder, metadata, options,
                     lambda n, m: update(job, progress=n, message=m), lambda: checkpoint(job))
    checkpoint(job)
    update(job, state="done", progress=100, message="完整乐谱已生成", result=result)


class Handler(BaseHTTPRequestHandler):
    server_version = "ScoreStitch/1.0"

    def log_message(self, fmt, *args):
        if args and "/api/jobs/" in str(args[0]):
            return
        super().log_message(fmt, *args)

    def json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        # Reject DNS rebinding and cross-site submissions to the local service.
        return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def do_GET(self):
        if not self.valid_host():
            return self.json(403, {"error": "只允许本机访问。"})
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health":
            return self.json(200, {"ok": True, "version": "1.0"})
        if path == "/api/jobs":
            with LOCK:
                jobs = [public(j) for j in reversed(list(JOBS.values()))]
            return self.json(200, {"jobs": jobs})
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})", path)
        if match:
            with LOCK:
                job = JOBS.get(match[1])
                return self.json(200, public(job)) if job else self.json(404, {"error": "任务不存在。"})
        match = re.fullmatch(r"/files/([a-f0-9]{32})/(preview\.jpg|header\.png|row-[0-9]{3}\.png|score\.png|thumbnail\.png|result\.json)", path)
        if match:
            file = DATA / match[1] / match[2]
        else:
            assets = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if path not in assets:
                return self.json(404, {"error": "页面不存在。"})
            file = ROOT / "web" / assets[path]
        if not file.is_file():
            return self.json(404, {"error": "文件不存在。"})
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(file.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if file.name == "score.png":
            self.send_header("Content-Disposition", "inline; filename=sheet-music.png")
        self.end_headers()
        with file.open("rb") as stream:
            while block := stream.read(256 * 1024):
                self.wfile.write(block)

    def do_POST(self):
        if not self.valid_host() or self.headers.get("X-Score-Tool") != "1":
            return self.json(403, {"error": "请从工具页面发起操作。"})
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
            return self.json(403, {"error": "不允许跨站请求。"})
        parsed = urllib.parse.urlparse(self.path)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > MAX_BYTES:
                return self.json(413, {"error": "文件为空或超过 1 GB。"})
            if parsed.path == "/api/upload":
                name = urllib.parse.parse_qs(parsed.query).get("name", ["本地乐谱视频"])[0]
                job = new_job(Path(name).stem[:100])
                update(job, state="uploading", message="正在接收视频")
                remaining = size
                self.connection.settimeout(120)
                try:
                    with (Path(job["path"]) / "source.mp4").open("wb") as out:
                        while remaining:
                            block = self.rfile.read(min(256 * 1024, remaining))
                            if not block:
                                raise ValueError("上传中断，请重试。")
                            out.write(block)
                            remaining -= len(block)
                except Exception:
                    update(job, state="error", message="上传中断，请重试。")
                    raise
                POOL.submit(run, job, lambda: prepare(job))
                return self.json(202, public(job))
            if size > 64 * 1024:
                return self.json(413, {"error": "请求过大。"})
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("请求格式无效。")
            if parsed.path == "/api/link":
                link = str(data.get("url", ""))
                from sources import parse_link
                parse_link(link)
                job = new_job("读取视频中…")
                POOL.submit(run, job, lambda: prepare(job, link))
                return self.json(202, public(job))
            match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/(process|cancel|preview|compose)", parsed.path)
            if not match or match[1] not in JOBS:
                return self.json(404, {"error": "任务不存在。"})
            job, action = JOBS[match[1]], match[2]
            if action == "cancel":
                job["cancel"].set()
                return self.json(200, {"ok": True})
            if job["state"] not in ("ready", "done", "error", "cancelled"):
                return self.json(409, {"error": "任务处理中，请稍后操作。"})
            if "video" not in job:
                raise ValueError("视频尚未读取成功，请重新提交。")
            folder = Path(job["path"])
            if action == "preview":
                at = float(data.get("at", 0))
                if not 0 <= at < job["video"]["duration"]:
                    raise ValueError("预览时间超出视频长度。")
                preview(folder / "source.mp4", folder / "preview.jpg", at)
                return self.json(200, {"ok": True})
            if action == "compose":
                if not job.get("result") or not isinstance(data.get("rows"), list):
                    raise ValueError("没有可重新排列的结果。")
                result = compose(folder, job["result"].copy(), data["rows"])
                update(job, result=result)
                return self.json(200, public(job))
            job["cancel"].clear()
            update(job, state="queued", progress=0, message="已加入处理队列")
            POOL.submit(run, job, lambda: process_job(job, data))
            return self.json(202, public(job))
        except (ValueError, TypeError, KeyError) as exc:
            self.json(400, {"error": str(exc)})
        except Exception:
            self.json(500, {"error": "操作未完成，请重试。"})


def main():
    parser = argparse.ArgumentParser(description="动态乐谱拼接工具：本地视频乐谱提取工具")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True)
    # Restore completed jobs only; never silently resume network or CPU work.
    for result_file in sorted(DATA.glob("*/result.json"), key=lambda p: p.stat().st_mtime):
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
            key = result_file.parent.name
            JOBS[key] = {"id": key, "title": result["title"], "state": "done", "progress": 100,
                         "message": "完整乐谱已生成", "result": result, "cancel": threading.Event(),
                         "path": str(result_file.parent), "created": result_file.stat().st_mtime,
                         **{k: result[k] for k in ("source", "author", "video")}}
        except (ValueError, KeyError, OSError):
            continue
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        raise SystemExit(f"端口 {args.port} 无法使用，可运行 python app.py --port 8766。\n{exc}")
    url = f"http://127.0.0.1:{args.port}"
    print(f"\n动态乐谱拼接工具已启动 → {url}\n文件保存在 {DATA}\n按 Ctrl+C 停止。\n", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("正在停止…", flush=True)
    finally:
        for job in JOBS.values():
            job["cancel"].set()
        server.server_close()
        POOL.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    main()
