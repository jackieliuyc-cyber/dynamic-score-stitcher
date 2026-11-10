"""Extract complete staff systems, track their position over time, and compose PNGs.

Deduplication is positional within a scrolling sequence, never a global image hash:
identical repeated rhythms at different positions must survive.
"""
import json
import math
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def notation_gray(rgb):
    # Red channel preserves blue selected notes as dark marks; removes no symbols.
    return rgb[:, :, 0]


def staves(rgb):
    gray = notation_gray(rgb)
    h, w = gray.shape
    dark = (gray < 175).astype(np.uint8)
    horizontal = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((1, max(30, w // 7)), np.uint8))
    strength = horizontal.mean(axis=1)
    ys = np.flatnonzero(strength > max(.24, float(strength.max()) * .60))
    clusters = []
    for y in ys:
        if clusters and y - clusters[-1][-1] <= 2:
            clusters[-1].append(int(y))
        else:
            clusters.append([int(y)])
    lines = [float(np.mean(group)) for group in clusters]
    systems = []
    i = 0
    while i + 4 < len(lines):
        group = lines[i:i + 5]
        gaps = np.diff(group)
        gap = float(np.median(gaps))
        if 3 <= gap <= h / 18 and np.max(np.abs(gaps - gap)) <= max(1.5, gap * .19):
            # Five staff lines, with space for cymbal marks, dynamics and lower stems.
            top, bottom = round(group[0] - gap * 6.3), round(group[-1] + gap * 3.8)
            if top >= 3 and bottom <= h - 3:
                systems.append({"y": group[0], "gap": gap, "top": top, "bottom": bottom})
            i += 5
        else:
            i += 1
    # Adjacent rows may have unusually tight spacing. Never take neighboring symbols.
    for first, second in zip(systems, systems[1:]):
        if first["bottom"] > second["top"]:
            boundary = round((first["y"] + 4 * first["gap"] + second["y"]) / 2)
            first["bottom"] = min(first["bottom"], boundary)
            second["top"] = max(second["top"], boundary)
    return systems


def scroll_shift(previous, current):
    """Estimate old-y minus new-y. Return None for a scene/page change.

    Several full-width strips propose translations; the complete overlapping area
    validates them. Include the left margin so measure numbers disambiguate repeats.
    """
    h, w = previous.shape
    scale = min(1., 720 / w)
    a = cv2.resize(previous, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    b = cv2.resize(current, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    hh, ww = a.shape
    if float(np.mean(cv2.absdiff(a, b))) < 3.5:
        return 0., 1.
    strip = max(25, hh // 4)
    candidates = {0}
    margin = max(3, int(hh * .07))
    for y in (margin, (hh - strip) // 2, hh - strip - margin):
        patch = a[y:y + strip, 5:ww - 5]
        if patch.std() < 5:
            continue
        scores = cv2.matchTemplate(b[:, 5:ww - 5], patch, cv2.TM_CCOEFF_NORMED).ravel()
        # Multiple peaks are essential when adjacent rows contain the same rhythm.
        for idx in np.argpartition(scores, -min(4, len(scores)))[-4:]:
            for d in (-1, 0, 1):
                candidates.add(int(y - idx + d))
    # Refine proposed shifts at native vertical resolution: resizing vertically
    # can make an incorrect, repeated row look sharper than the correct row.
    native_candidates = {round(v / scale) + d for v in candidates for d in (-1, 0, 1)}
    aa_full = cv2.GaussianBlur(previous[:, ::2].astype(np.float32), (3, 3), .65)
    bb_full = cv2.GaussianBlur(current[:, ::2].astype(np.float32), (3, 3), .65)
    margin = max(3, int(h * .07))
    best = None
    for shift in native_candidates:
        # A reading sequence progresses down the score. Repeated rhythms can
        # otherwise spuriously align to a row above the previous viewport.
        if shift < -2:
            continue
        lo, hi = max(margin, -shift + margin), min(h - margin, h - shift - margin)
        if hi - lo < h * .30:
            continue
        aa = aa_full[lo + shift:hi + shift]
        bb = bb_full[lo:hi]
        active = (aa < 220) | (bb < 220)
        if active.sum() < 100:
            continue
        loss = float(np.abs(aa - bb)[active].mean()) / 255
        # Distinct measure labels in the left margin get extra weight.
        left = active[:, :max(18, ww // 15)]
        if left.sum() > 20:
            loss += .25 * float(np.abs(aa - bb)[:, :left.shape[1]][left].mean()) / 255
        # For ambiguous repeated grooves prefer the shortest plausible movement.
        # Use the unpenalized loss for confidence so true large scrolls still work.
        rank = loss + .12 * abs(shift) / h
        if best is None or rank < best[0]:
            best = rank, shift, loss
    if best is None or best[2] > .19:
        return None, 0.
    return float(best[1]), max(0., 1 - best[2])


def quality(rgb):
    a = rgb.astype(np.int16)
    blue = (a[:, :, 2] - a[:, :, 0] > 14) & (a[:, :, 2] - a[:, :, 1] > 4)
    # Playback rectangles are far more disruptive than small, selected note heads.
    pale_blue = blue & (a[:, :, 0] > 100)
    return int(pale_blue.sum()) * 4 + int(blue.sum())


def measure_labels_changed(previous, current, systems):
    """Detect a stationary page replacement even when the grooves are identical."""
    changed = 0
    left = max(30, round(current.shape[1] * .065))
    for system in systems:
        lo = max(0, round(system['y'] - 4 * system['gap']))
        hi = max(lo, round(system['y'] - system['gap']))
        a = previous[lo:hi, :left] < 150
        b = current[lo:hi, :left] < 150
        union = int((a | b).sum())
        if min(int(a.sum()), int(b.sum())) > 8 and union > 15:
            if int((a ^ b).sum()) / union > .30:
                changed += 1
    return changed >= 2


def font(size):
    for path in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def compose(folder, metadata, selected=None):
    rows = metadata["rows"]
    by_id = {row["id"]: row for row in rows}
    if selected is None:
        selected = [row["id"] for row in rows]
    if not selected or len(selected) > 500 or len(set(selected)) != len(selected):
        raise ValueError("请至少保留一行谱面，且不要重复选择同一行。")
    if any(item not in by_id for item in selected):
        raise ValueError("选择了不存在的谱行。")
    images = [Image.open(folder / by_id[item]["file"]).convert("L") for item in selected]
    width = max(image.width for image in images)
    pad = max(20, width // 35)
    linegap = max(10, width // 85)
    head = Image.open(folder / "header.png").convert("L") if (folder / "header.png").exists() else None
    header_h = head.height + 20 if head else 0
    height = 110 + header_h + sum(im.height + linegap for im in images) + 75
    if (width + pad * 2) * height > 100_000_000:
        raise ValueError("谱图过大，请缩短选取的时间段再生成。")
    out = Image.new("L", (width + pad * 2, height), 255)
    draw = ImageDraw.Draw(out)
    title = metadata.get("title", "完整鼓谱")
    title_font = font(max(22, width // 36))
    while draw.textlength(title, font=title_font) > width and len(title) > 8:
        title = title[:-2] + "…"
    draw.text((pad, 24), title, font=title_font, fill=20)
    small = font(max(13, width // 80))
    draw.text((pad, 72), f"视频截图拼接 · {len(images)} 行 · 保留原谱演奏记号", font=small, fill=100)
    y = 110
    if head:
        out.paste(head, (pad, y))
        y += header_h
    for image in images:
        out.paste(image, (pad, y))
        y += image.height + linegap
    credit = metadata.get("author") or "本地视频"
    draw.text((pad, height - 58), "来源：" + credit[:75], font=small, fill=110)
    source = metadata.get("source", "")
    if source:
        draw.text((pad, height - 32), source[:110], font=small, fill=110)
    target = folder / "score.png"
    temp = folder / "score.pending.png"
    out.save(temp, optimize=True, dpi=(150, 150))
    temp.replace(target)
    thumb = out.copy()
    thumb.thumbnail((640, 2400))
    thumb.save(folder / "thumbnail.png")
    metadata["selected"] = selected
    metadata["output_size"] = list(out.size)
    (folder / "result.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def extract(source, folder, metadata, options, progress, check_cancel):
    info = metadata["video"]
    start = float(options.get("start", 0))
    end = float(options.get("end") or info["duration"])
    interval = float(options.get("interval", 1))
    if not all(math.isfinite(x) for x in (start, end, interval)) or not 0 <= start < end <= info["duration"] + .05:
        raise ValueError("时间范围无效。")
    if not .4 <= interval <= 3:
        raise ValueError("采样间隔需在 0.4 至 3 秒之间。")
    crop = options.get("crop", [0, 0, 1, 1])
    if len(crop) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in crop):
        raise ValueError("谱面区域参数无效。")
    x0, y0, x1, y1 = crop
    if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1 or x1 - x0 < .15 or y1 - y0 < .1:
        raise ValueError("谱面区域太小，请重新框选。")
    # Decode once, streaming only sampled frames. Memory does not grow with duration.
    width = min(1280, info["width"])
    height = max(2, round(info["height"] * width / info["width"] / 2) * 2)
    bounds = [round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height)]
    if bounds[2] - bounds[0] < 160 or bounds[3] - bounds[1] < 80:
        raise ValueError("框选区域分辨率太低，请扩大谱面区域。")
    interval = max(interval, (end - start) / 1800)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(start), "-i", str(source),
        "-t", str(end - start), "-vf", f"fps=1/{interval},scale={width}:{height}",
        "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    records = []
    segment = 0
    offset = 0.
    previous = None
    frame_index = 0
    page_breaks = 0
    warnings = []
    frame_bytes = width * height * 3
    log = (folder / "ffmpeg.log").open("wb")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
    try:
        while True:
            check_cancel()
            raw = process.stdout.read(frame_bytes)
            if not raw:
                break
            if len(raw) != frame_bytes:
                raise ValueError("视频解码中断，请尝试重新下载或转换为 MP4。")
            frame = np.frombuffer(raw, np.uint8).reshape(height, width, 3)
            frame = frame[bounds[1]:bounds[3], bounds[0]:bounds[2]].copy()
            systems = staves(frame)
            timestamp = start + frame_index * interval
            frame_index += 1
            if frame_index % 3 == 0:
                progress(min(94, 5 + int((timestamp - start) / (end - start) * 89)),
                         f"识别谱行 · {timestamp:.0f} / {end:.0f} 秒 · 已找到 {len(records)} 行")
            if not systems:
                continue
            gray = notation_gray(frame)
            if previous is not None:
                shift, confidence = scroll_shift(previous, gray)
                if shift is not None and abs(shift) < 2 and measure_labels_changed(previous, gray, systems):
                    shift = None
                if shift is None:
                    # A page change with no reliable overlap is kept as a new segment.
                    segment += 1
                    offset = 0.
                    page_breaks += 1
                else:
                    offset += shift
            previous = gray.copy()
            if not records:
                top = systems[0]["top"]
                header = frame[:max(0, top - 8)]
                if header.shape[0] > 40:
                    ink = np.where((header.min(axis=2) < 160).mean(axis=1) > .002)[0]
                    # Keep original tempo/title only if it isn't a clipped preceding staff.
                    if len(ink) and not staves(header):
                        hh = header[max(0, ink[0] - 8):min(len(header), ink[-1] + 10)]
                        Image.fromarray(hh).convert("L").save(folder / "header.png")
            for system in systems:
                position = system["y"] + offset
                image = frame[system["top"]:system["bottom"]].copy()
                penalty = quality(image)
                existing = next((r for r in reversed(records) if r["segment"] == segment and
                                 abs(r["position"] - position) < system["gap"] * 3.3), None)
                if existing is None:
                    record = {"id": f"row-{len(records) + 1:03}", "segment": segment,
                              "position": position, "time": round(timestamp, 2),
                              "penalty": penalty, "gap": system["gap"], "seen": 1}
                    record["file"] = record["id"] + ".png"
                    records.append(record)
                    existing = record
                    save = True
                else:
                    existing["seen"] += 1
                    # Following the measured position prevents subpixel drift accumulation.
                    existing["position"] = existing["position"] * .8 + position * .2
                    save = penalty < existing["penalty"]
                if save:
                    existing["penalty"] = penalty
                    existing["time"] = round(timestamp, 2)
                    # Contrast correction only. Do not reconstruct or invent any notation.
                    clean = np.clip((image[:, :, 0].astype(float) - 10) * 255 / 237, 0, 255).astype(np.uint8)
                    Image.fromarray(clean).save(folder / existing["file"])
            if len(records) > 500:
                raise ValueError("识别结果超过 500 行，可能包含演奏画面。请缩小谱面区域或时间范围。")
        code = process.wait(timeout=20)
        if code:
            raise ValueError("视频解码失败，请重新下载或上传其他格式。")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stdout.close()
        log.close()
    if not records:
        raise ValueError("没有识别到完整的五线谱。请框选谱面区域，或选择鼓谱清晰可见的时间段。")
    records.sort(key=lambda r: (r["segment"], r["position"]))
    if page_breaks:
        warnings.append(f"检测到 {page_breaks} 次无法连续对齐的画面切换，请检查切换附近是否重行或漏行。")
    if any(r["penalty"] > 500 for r in records):
        warnings.append("部分谱行始终带有彩色标记，已转为灰度，请与原视频核对。")
    if len(records) < 2:
        warnings.append("只识别到一行谱面。若视频为横向滚动，当前版本无法保证完整，请检查结果。")
    metadata.update({"rows": records, "warnings": warnings, "sample_count": frame_index,
                     "page_breaks": page_breaks, "options": options})
    progress(96, "排列谱行并生成完整图片")
    check_cancel()
    return compose(folder, metadata)
