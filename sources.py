"""Public Bilibili video ingestion. No browser cookies or login credentials needed."""
import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

MAX_BYTES = 1024 * 1024 * 1024
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=35)


def api(path, params):
    with request("https://api.bilibili.com" + path + "?" + urllib.parse.urlencode(params)) as r:
        data = json.load(r)
    if data.get("code") != 0:
        raise ValueError("视频来源未能提供视频，请稍后重试或上传本地视频。")
    return data["data"]


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


def download(link, folder, progress, check_cancel):
    bvid, part = parse_link(link)
    progress(3, "读取视频信息")
    info = api("/x/web-interface/view", {"bvid": bvid})
    pages = info.get("pages", [])
    if part > len(pages):
        raise ValueError("视频没有指定的分段。")
    page = pages[part - 1]
    if page.get("duration", 0) > 1800:
        raise ValueError("当前版本支持 30 分钟以内的视频。长视频请先裁剪后上传。")
    play = api("/x/player/playurl", {
        "bvid": bvid, "cid": page["cid"], "qn": 80,
        "fnval": 0, "fnver": 0, "fourk": 1,
    })
    streams = play.get("durl", [])
    if not streams:
        raise ValueError("视频来源未返回可读取的画面，请使用「本地视频」导入文件。")
    if len(streams) != 1:
        raise ValueError("此视频返回多段媒体，请下载为一个完整视频后上传。")
    stream = streams[0]
    dest = folder / "source.mp4"
    total = stream.get("size", 0)
    if total > MAX_BYTES:
        raise ValueError("视频超过 1 GB，请先裁剪或压缩。")
    urls = [stream["url"]] + (stream.get("backup_url") or [])
    error = None
    for url in urls:
        # Only use Bilibili's media CDN addresses returned by the public API.
        host = urllib.parse.urlparse(url).hostname or ""
        if not host.endswith((".bilivideo.com", ".bilivideo.cn", ".bilivideo.net", ".acgvideo.com")):
            continue
        try:
            with request(url) as response, dest.open("wb") as out:
                size = 0
                while True:
                    check_cancel()
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("视频超过 1 GB，请先裁剪或压缩。")
                    out.write(chunk)
                    progress(min(90, 10 + int(size / max(total, size) * 80)), "下载视频画面")
            if total and size != total:
                raise ValueError("视频下载不完整，请重试。")
            error = None
            break
        except (OSError, ValueError) as exc:
            error = exc
    if error or not dest.exists():
        raise ValueError("视频下载失败，请重试或上传本地视频。") from error
    return dest, {
        "title": info["title"] if part == 1 else info["title"] + " · " + page["part"],
        "source": f"https://www.bilibili.com/video/{bvid}/?p={part}",
        "author": info.get("owner", {}).get("name", ""),
        "quality": play.get("quality"),
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
