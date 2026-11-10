"""Local video ingestion using yt-dlp, without browser credentials or cached media."""
import json
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_BYTES = 1024 * 1024 * 1024
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}


def describe_error(error):
    """Actionable UI errors without leaking URLs, cookies or local paths."""
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403, 412):
            return (f"视频来源拒绝自动读取（HTTP {error.code}）。请先在浏览器打开视频确认可播放；"
                    "若仍无法读取，请选择「本地视频」导入文件。")
        if error.code == 429:
            return "视频来源请求过于频繁（HTTP 429），请稍后再试，或使用「本地视频」。"
        if error.code == 404:
            return "未找到视频资源（HTTP 404），请检查链接是否有效，或使用「本地视频」。"
        return f"视频来源请求失败（HTTP {error.code}），请稍后重试，或使用「本地视频」。"
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(cause, ssl.SSLCertVerificationError):
        return "HTTPS 证书校验失败，请检查系统时间及 Python 证书配置，或使用「本地视频」。"
    if isinstance(cause, (TimeoutError, socket.timeout)):
        return "连接视频来源超时，请检查网络后重试，或使用「本地视频」。"
    if isinstance(cause, socket.gaierror):
        return "无法解析视频来源地址，请检查网络和 DNS 设置后重试。"
    if isinstance(error, urllib.error.URLError):
        return "无法连接视频来源，请检查网络及代理设置，或使用「本地视频」。"
    if isinstance(error, subprocess.TimeoutExpired):
        return "视频解码或预览生成超时，请缩短视频，或转换为 MP4 后重试。"
    if isinstance(error, subprocess.CalledProcessError):
        return "视频解码失败，请确认文件完整且可播放，或转换为 MP4 后重试。"
    if isinstance(error, ValueError):
        return str(error)
    return "处理失败。请查看启动窗口中的错误详情后重试。"


def parse_link(link):
    link = link.strip()
    if re.fullmatch(r"BV[0-9A-Za-z]{10}", link):
        return link, 1
    url = urllib.parse.urlparse(link)
    if url.scheme not in ("https", "http") or url.hostname not in (
        "www.bilibili.com", "bilibili.com", "m.bilibili.com", "b23.tv"
    ) or url.username or url.password or url.port not in (None, 80, 443):
        raise ValueError("暂不支持此视频来源，请输入已适配的视频链接，或上传本地视频。")
    if url.hostname == "b23.tv":
        # Do not follow arbitrary redirects: validate every destination first.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        for _ in range(5):
            try:
                with opener.open(urllib.request.Request(link, headers=HEADERS), timeout=20) as r:
                    link = r.url
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308):
                    raise
                link = urllib.parse.urljoin(link, exc.headers.get("Location", ""))
                dest = urllib.parse.urlparse(link)
                if dest.scheme not in ("https", "http") or dest.hostname not in (
                    "www.bilibili.com", "bilibili.com", "m.bilibili.com", "b23.tv"
                ) or dest.username or dest.password or dest.port not in (None, 80, 443):
                    raise ValueError("分享链接跳转到了不支持的地址。")
                if dest.hostname != "b23.tv":
                    break
        url = urllib.parse.urlparse(link)
    match = re.search(r"/video/(BV[0-9A-Za-z]{10})(?:/|$)", url.path)
    if not match:
        raise ValueError("未能识别视频地址，请复制具体视频的页面链接，或上传本地视频。")
    page = int(urllib.parse.parse_qs(url.query).get("p", ["1"])[0])
    if page < 1:
        raise ValueError("视频分段编号应大于 0。")
    return match.group(1), page


def downloader_error(error):
    """Keep remote URLs and credentials out of UI messages."""
    text = str(error)
    match = re.search(r'(?:HTTP(?: Error)?[ :]+|server \()(\d{3})', text, re.I)
    if match:
        return describe_error(urllib.error.HTTPError('', int(match[1]), '', {}, None))
    if 'timed out' in text.lower() or 'timeout' in text.lower():
        return "连接视频来源超时，请检查网络后重试，或使用「本地视频」。"
    return "yt-dlp 未能读取该视频，请尝试更新下载组件，或使用「本地视频」。"


def download(link, folder, progress, check_cancel):
    bvid, part = parse_link(link)
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise ValueError("缺少视频下载组件，请重新运行启动脚本安装依赖。") from exc
    canonical = f"https://www.bilibili.com/video/{bvid}/?p={part}"
    check_cancel()
    progress(3, "读取视频信息")

    class Logger:
        def debug(self, message):
            check_cancel()
        info = warning = error = debug

    def validate(info, *, incomplete=False):
        check_cancel()
        if info.get('is_live'):
            raise ValueError("暂不支持直播，请选择已录制的视频。")
        if (info.get('duration') or 0) > 1800:
            raise ValueError("当前版本支持 30 分钟以内的视频。长视频请先裁剪后上传。")
        if (info.get('filesize') or 0) > MAX_BYTES:
            raise ValueError("视频超过 1 GB，请先裁剪或压缩。")

    def hook(event):
        check_cancel()
        size = event.get('downloaded_bytes') or 0
        total = event.get('total_bytes') or event.get('total_bytes_estimate') or 0
        if size > MAX_BYTES:
            raise ValueError("视频超过 1 GB，请先裁剪或压缩。")
        if event.get('status') == 'downloading':
            progress(min(90, 10 + int(size / max(total, size, 1) * 80)), "下载视频画面")

    # Each attempt gets an empty workspace: no previous video or .part is reused.
    with tempfile.TemporaryDirectory(prefix='.download-', dir=folder) as temp:
        target = Path(temp) / 'source.mp4'
        options = {
            'format': 'bestvideo[ext=mp4][height<=1080]/best[ext=mp4][height<=1080]',
            'outtmpl': str(target), 'noplaylist': True,
            'cachedir': False, 'continuedl': False, 'overwrites': True,
            'cookiefile': None, 'cookiesfrombrowser': None, 'usenetrc': False,
            'download_archive': None, 'socket_timeout': 35,
            'retries': 0, 'fragment_retries': 0, 'extractor_retries': 0,
            'skip_unavailable_fragments': False, 'max_filesize': MAX_BYTES,
            'match_filter': validate, 'progress_hooks': [hook],
            'logger': Logger(), 'quiet': True, 'noprogress': True,
        }
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(canonical, download=True)
        except DownloadError as exc:
            check_cancel()
            raise ValueError(downloader_error(exc)) from exc
        check_cancel()
        if not info or info.get('_type', 'video') != 'video':
            raise ValueError("视频来源未返回单个视频，请检查链接。")
        if not target.is_file() or not 0 < target.stat().st_size <= MAX_BYTES:
            raise ValueError("视频未完整下载，或文件超过 1 GB，请重试或使用「本地视频」。")
        validate(info)
        dest = folder / 'source.mp4'
        target.replace(dest)
    return dest, {
        'title': info.get('title') or bvid, 'source': canonical,
        'author': info.get('uploader') or '', 'quality': info.get('height'),
    }


def probe(path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ValueError("未找到 FFmpeg。macOS 可运行 brew install ffmpeg，安装后重新启动。")
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height:format=duration", "-of", "json", str(path),
    ], capture_output=True, timeout=30, check=True)
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    if not streams:
        raise ValueError("文件中没有可读取的视频画面。")
    duration = float(info.get("format", {}).get("duration", 0))
    if not 1 <= duration <= 1800:
        raise ValueError("当前版本支持 1 秒至 30 分钟的视频。")
    if not 32 <= streams[0]["width"] <= 8192 or not 32 <= streams[0]["height"] <= 8192:
        raise ValueError("视频画面尺寸不受支持。")
    return {"width": streams[0]["width"], "height": streams[0]["height"], "duration": duration}


def preview(path, dest, at=0):
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(at),
        "-i", str(path), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", str(dest),
    ], capture_output=True, timeout=40, check=True)
