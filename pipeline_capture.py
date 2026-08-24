# -*- coding: utf-8 -*-
"""小红书 / 抖音内容采集流水线。

用法：
  python pipeline_capture.py xhs 关键词 [--max 20]
  python pipeline_capture.py dy 关键词 [--max 20]
  python pipeline_capture.py dyvideo 视频链接
"""
from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from read_social import (
    JS_INITIAL_STATE,
    cmd_search_dy,
    cmd_search_xhs,
    connect,
    extract_links,
    page_text,
    tidy,
    xhs_note_detail,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(os.environ.get("SOCIALREADER_OUTPUT_ROOT", r"D:\ObsidianVault\采集\内容流水线")).expanduser()
VIDEO_DIR = Path(os.environ.get("SOCIALREADER_MEDIA_ROOT", str(ROOT / "videos"))).expanduser()
PYTHON = Path(sys.executable)
ASR_SCRIPT = ROOT / "asr_video.py"
HOST = "127.0.0.1"
PORT = 9333
MAX_COMMENTS = 10
PLATFORM_LABEL = {"xhs": "小红书", "dy": "抖音", "dyvideo": "抖音"}


@dataclass
class Capture:
    title: str = ""
    author: str = ""
    published_at: str = ""
    body: str = ""
    interactions: str = ""
    comments: list[str] = field(default_factory=list)
    transcript: str = ""
    video_note: str = ""
    content_type: str = ""
    images: list[str] = field(default_factory=list)
    media_note: str = ""


def check_debug_port() -> bool:
    """在导入的 connect() 之前给出更直接的 9333 端口诊断。"""
    try:
        with socket.create_connection((HOST, PORT), timeout=2):
            return True
    except OSError as exc:
        print("[连接失败] 未检测到 127.0.0.1:9333。")
        print("请先双击 start_browser.bat 启动调试浏览器，再运行本工具。")
        print(f"详情: {exc}")
        return False


def login_gate(page: Any, platform: str) -> None:
    """每次启动都先打开对应网站，并等待用户确认调试浏览器已登录。"""
    login_url = (
        "https://www.xiaohongshu.com"
        if platform == "xhs"
        else "https://www.douyin.com"
    )
    print(f"\n[第 0 步] 正在打开 {PLATFORM_LABEL[platform]} 登录页：{login_url}")
    try:
        page.get(login_url, timeout=20)
    except Exception as exc:
        print(f"[提示] 登录页跳转异常，请在调试浏览器中手动打开：{exc}")
    print("\n" + "=" * 68)
    print("请在调试浏览器窗口中扫码/登录小红书和抖音，登录完成后按回车继续")
    print("=" * 68)
    input()


def safe_component(value: str, fallback: str = "未命名", limit: int = 60) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = fallback
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "_" + value
    return value[:limit].rstrip(" .") or fallback


def clean_inline(value: Any, fallback: str = "未获取") -> str:
    text = tidy(str(value or ""))
    text = re.sub(r"[\r\n]+", " ", text).strip()
    return text or fallback


def clean_block(value: Any) -> str:
    return tidy(html.unescape(str(value or ""))).strip()


def format_published(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        if number > 1_000_000_000:
            return datetime.fromtimestamp(number).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    return clean_inline(value, "")


def normalize_url(url: str, base: str) -> str:
    return urljoin(base, html.unescape(url or ""))


def unique_links(items: list[tuple[str, str]], base: str, maximum: int) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for title, href in items:
        url = normalize_url(href, base)
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        output.append((clean_inline(title, ""), url))
        if len(output) >= maximum:
            break
    return output


def parse_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def element_text(page: Any, selectors: list[str], timeout: float = 1.5) -> str:
    for selector in selectors:
        try:
            element = page.ele(selector, timeout=timeout)
            text = clean_block(element.text if element else "")
            if text:
                return text
        except Exception:
            continue
    return ""


def extract_comments(page: Any, maximum: int = MAX_COMMENTS) -> list[str]:
    selectors = [
        ".comment-item",
        ".comment-inner-container",
        "css:[data-e2e*='comment-item']",
        "css:[class*='comment-item']",
    ]
    comments: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        try:
            elements = page.eles(selector, timeout=2)
        except Exception:
            continue
        for element in elements:
            try:
                text = clean_block(element.text or "")
            except Exception:
                continue
            if text and text not in seen:
                seen.add(text)
                comments.append(text[:1200])
                if len(comments) >= maximum:
                    return comments
        if comments:
            return comments

    fallback = element_text(
        page,
        [".comments-container", "css:[data-e2e*='comment-list']", "css:[class*='comment-list']"],
        timeout=2,
    )
    if fallback:
        chunks = [clean_block(x) for x in re.split(r"\n{2,}", fallback) if clean_block(x)]
        return chunks[:maximum]
    return []


XHS_VIDEO_JS = r"""
const st = window.__INITIAL_STATE__;
const map = (st && st.note && st.note.noteDetailMap) || {};
const detail = map[Object.keys(map)[0]];
const note = detail && detail.note;
if (!note) return '';
const rows = [];
const seen = new Set();
function walk(value, depth) {
  if (!value || depth > 8) return;
  if (Array.isArray(value)) {
    for (const item of value) walk(item, depth + 1);
    return;
  }
  if (typeof value !== 'object') return;
  const master = value.masterUrl || value.master_url || '';
  const backups = value.backupUrls || value.backup_urls || [];
  for (const url of [master, ...(Array.isArray(backups) ? backups : [])]) {
    if (/^https?:/i.test(url) && !seen.has(url)) {
      seen.add(url);
      rows.push({url, size: Number(value.size || 0), width: Number(value.width || 0)});
    }
  }
  for (const child of Object.values(value)) walk(child, depth + 1);
}
walk(note.video || {}, 0);
rows.sort((a, b) => (a.size || Number.MAX_SAFE_INTEGER) - (b.size || Number.MAX_SAFE_INTEGER));
return JSON.stringify({type: note.type || '', urls: rows.map(x => x.url)});
"""


def capture_xhs(page: Any, url: str, video_path: Path, model: str) -> Capture:
    page.get(url)
    # 必须调用现有的详情逻辑：它负责等待异步容器，并以 .desc 兜底。
    detail_found = xhs_note_detail(page)
    try:
        info = parse_json(page.run_js(JS_INITIAL_STATE))
    except Exception:
        info = {}

    expected_id = re.search(r"/(?:explore|discovery|search_result)/(\w+)", url)
    current_url = str(getattr(page, "url", "") or "")
    if expected_id and expected_id.group(1) not in current_url:
        raise RuntimeError("详情链接被重定向，可能缺少 xsec_token 或遇到风控")
    desc = clean_block(info.get("desc")) or element_text(page, [".desc"], timeout=3)
    title = clean_inline(info.get("title"), "")
    if not title:
        title = clean_inline(getattr(page, "title", ""), "小红书笔记")
    author = clean_inline(info.get("author"))
    published = format_published(info.get("time"))
    has_note_info = bool(info.get("title") or info.get("desc"))
    interactions = (
        f"{info.get('likes', 0)}赞 / {info.get('collects', 0)}藏 / "
        f"{info.get('comments', 0)}评 / {info.get('shares', 0)}分享"
        if has_note_info
        else "未获取"
    )

    try:
        page.run_js("window.scrollTo(0, Math.max(document.body.scrollHeight * 0.65, 500));")
        time.sleep(1.5)
    except Exception:
        pass
    comments = extract_comments(page)
    if not desc:
        raise RuntimeError("详情正文为空，可能遇到登录拦截、滑块或页面结构变化")
    try:
        video_info = parse_json(page.run_js(XHS_VIDEO_JS))
    except Exception:
        video_info = {}
    note_type = str(info.get("type") or video_info.get("type") or "")
    urls = [normalize_video_candidate(value) for value in video_info.get("urls", [])]
    is_video = note_type.lower() == "video" or bool(urls)
    transcript = ""
    video_note = ""
    if is_video:
        downloaded, reason = download_video(page, urls, video_path, url)
        if downloaded:
            print(f"  [视频] 已下载 {downloaded.name} ({downloaded.stat().st_size / 1024 / 1024:.1f} MB)")
            transcript, asr_reason = run_asr(downloaded, model)
            if transcript:
                print("  [转写] 成功")
            else:
                reason = asr_reason
                print(f"  [转写降级] {reason}")
        else:
            print(f"  [视频降级] {reason}")
        if not transcript:
            video_note = f"仅保存正文和评论；{reason or '未生成转写'}"
    return Capture(
        title=title,
        author=author,
        published_at=published,
        body=desc,
        interactions=interactions,
        comments=comments,
        transcript=transcript,
        video_note=video_note,
        content_type="视频" if is_video else "图文",
    )


DY_DETAIL_JS = r"""
const text = (sel) => {
  const el = document.querySelector(sel);
  return el ? (el.innerText || el.textContent || '').trim() : '';
};
const meta = (sel) => {
  const el = document.querySelector(sel);
  return el ? (el.content || '') : '';
};
const videoUrls = [];
for (const v of document.querySelectorAll('video, video source')) {
  for (const u of [v.currentSrc, v.src, v.getAttribute('src')]) {
    if (u && /^https?:/i.test(u)) videoUrls.push(u);
  }
}
const domImageUrls = [...document.images]
  .map(img => img.currentSrc || img.src || '')
  .filter(url => /^https?:/i.test(url) && /biz_tag=aweme_images|tplv-dy-aweme-images/i.test(url));
const states = [window.__INITIAL_STATE__, window._ROUTER_DATA, window.__SSR_DATA__];
const stateUrls = [];
const imageUrls = [];
const interesting = {};
let visited = new WeakSet();
let count = 0;
function walk(obj, depth, trail = '') {
  if (!obj || typeof obj !== 'object' || depth > 8 || count++ > 25000) return;
  if (visited.has(obj)) return;
  visited.add(obj);
  for (const [k, v] of Object.entries(obj)) {
    const key = String(k).toLowerCase();
    if (typeof v === 'string') {
      const context = (trail + ' ' + key).slice(-240);
      if (/^https?:/i.test(v) && (
          /(play|download|video|bitrate|url.list)/i.test(context) ||
          /\.mp4(?:\?|$)|\/video\/play|mime_type=video/i.test(v)
      )) stateUrls.push(v);
      if (/^https?:/i.test(v) && /douyinpic|byteimg/i.test(v) &&
          /(images|image.list|image.url|origin.image)/i.test(context) &&
          !/(avatar|comment|emoji)/i.test(context)) imageUrls.push(v);
      if (!interesting.desc && /(desc|description|title)/.test(key) && v.length > 3 && v.length < 5000) interesting.desc = v;
      if (!interesting.author && /(nickname|authorname|uniqueid)/.test(key) && v.length < 300) interesting.author = v;
      if (/(diggcount|likecount)/.test(key) && interesting.likes == null) interesting.likes = v;
      if (/(commentcount)/.test(key) && interesting.comments == null) interesting.comments = v;
      if (/(sharecount)/.test(key) && interesting.shares == null) interesting.shares = v;
      if (/(collectcount)/.test(key) && interesting.collects == null) interesting.collects = v;
      if (/(createtime|publishtime)/.test(key) && interesting.time == null) interesting.time = v;
    } else if (typeof v === 'number' || typeof v === 'string') {
      if (/(diggcount|likecount)/.test(key) && interesting.likes == null) interesting.likes = v;
      if (/(commentcount)/.test(key) && interesting.comments == null) interesting.comments = v;
      if (/(sharecount)/.test(key) && interesting.shares == null) interesting.shares = v;
      if (/(collectcount)/.test(key) && interesting.collects == null) interesting.collects = v;
      if (/(createtime|publishtime)/.test(key) && interesting.time == null) interesting.time = v;
      if (/(awemetype|aweme_type)/.test(key) && interesting.awemeType == null) interesting.awemeType = v;
    } else {
      walk(v, depth + 1, (trail + ' ' + key).slice(-240));
    }
  }
}
for (const st of states) walk(st, 0);
return JSON.stringify({
  title: text('h1') || meta("meta[property='og:title']") || document.title || '',
  desc: text("[data-e2e='video-desc']") || text("[class*='video-info-detail']") ||
        meta("meta[property='og:description']") || meta("meta[name='description']") || interesting.desc || '',
  author: text("[data-e2e='video-author-name']") || text("[class*='author']") || interesting.author || '',
  time: interesting.time || '',
  likes: interesting.likes,
  comments: interesting.comments,
  shares: interesting.shares,
  collects: interesting.collects,
  awemeType: interesting.awemeType,
  videoUrls: [...new Set(videoUrls.concat(stateUrls))].slice(0, 80),
  imageUrls: [...new Set(domImageUrls.concat(imageUrls))].slice(0, 30)
});
"""


def normalize_video_candidate(value: str) -> str:
    value = html.unescape(str(value or "")).replace("\\u002F", "/").replace("\\/", "/")
    try:
        value = unquote(value)
    except Exception:
        pass
    return value.strip()


def video_candidates(page: Any, info: dict[str, Any]) -> list[str]:
    candidates = [normalize_video_candidate(x) for x in info.get("videoUrls", [])]
    # 页面状态路径变化时，从 HTML 中再找一次显式媒体链接。
    try:
        source = str(getattr(page, "html", "") or "")
    except Exception:
        source = ""
    patterns = [
        r'https?:\\?/\\?/[^"\'<> ]+?(?:\.mp4|video\/play)[^"\'<> ]*',
        r'"(?:playAddr|playApi|play_url|downloadAddr)"\s*:\s*"([^"]+)"',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, source, flags=re.I):
            candidates.append(normalize_video_candidate(match))
    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.startswith(("http://", "https://")):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        output.append(candidate)
    return output


def browser_cookie_header(page: Any) -> str:
    try:
        cookies = page.cookies()
    except Exception:
        return ""
    pairs: list[str] = []
    if isinstance(cookies, dict):
        pairs = [f"{k}={v}" for k, v in cookies.items()]
    elif isinstance(cookies, list):
        for item in cookies:
            if isinstance(item, dict) and item.get("name"):
                pairs.append(f"{item['name']}={item.get('value', '')}")
    return "; ".join(pairs)


def download_video(page: Any, urls: list[str], destination: Path, referer: str) -> tuple[Path | None, str]:
    if not urls:
        return None, "页面中未发现可下载的视频 URL"
    destination.parent.mkdir(parents=True, exist_ok=True)
    cookie = browser_cookie_header(page)
    errors: list[str] = []
    for index, url in enumerate(urls[:8], start=1):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
            "Referer": referer,
            "Accept": "video/webm,video/mp4,video/*;q=0.9,*/*;q=0.5",
        }
        if cookie:
            headers["Cookie"] = cookie
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=30) as response:
                content_type = (response.headers.get("Content-Type") or "").lower()
                first = response.read(65536)
                if not first:
                    raise RuntimeError("响应为空")
                if "text/html" in content_type or first.lstrip().startswith((b"<html", b"<!DOCTYPE")):
                    raise RuntimeError(f"返回了网页而非视频 ({content_type or 'unknown'})")
                total = len(first)
                with destination.open("wb") as handle:
                    handle.write(first)
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        total += len(chunk)
                        if total > 1024 * 1024 * 1024:
                            raise RuntimeError("视频超过 1GB，已停止下载")
            if destination.stat().st_size < 100_000:
                raise RuntimeError(f"文件过小 ({destination.stat().st_size} bytes)")
            return destination, ""
        except Exception as exc:
            errors.append(f"候选{index}: {exc}")
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
    return None, "; ".join(errors[-3:]) or "视频下载失败"


def download_images(
    page: Any,
    urls: list[str],
    asset_dir: Path,
    prefix: str,
    referer: str,
    maximum: int = 12,
) -> tuple[list[str], list[str]]:
    asset_dir.mkdir(parents=True, exist_ok=True)
    cookie = browser_cookie_header(page)
    dom_sources: dict[str, Any] = {}
    try:
        for element in page.eles("css:img[src*='biz_tag=aweme_images']", timeout=2):
            source_url = normalize_video_candidate(element.attr("src") or "")
            if source_url:
                dom_sources.setdefault(source_url, element)
    except Exception:
        pass
    saved: list[str] = []
    errors: list[str] = []
    for index, url in enumerate(urls[:maximum], start=1):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        if cookie:
            headers["Cookie"] = cookie
        destination = asset_dir / f"{prefix}_{index:02d}.jpg"
        try:
            content_type = ""
            element = dom_sources.get(normalize_video_candidate(url))
            if element is not None:
                data = element.src(timeout=20)
                if not isinstance(data, bytes):
                    raise RuntimeError("浏览器未返回图片字节")
            else:
                with urlopen(Request(url, headers=headers), timeout=30) as response:
                    content_type = (response.headers.get("Content-Type") or "").lower()
                    data = response.read(25 * 1024 * 1024 + 1)
            if not data or len(data) > 25 * 1024 * 1024:
                raise RuntimeError("图片为空或超过 25MB")
            if "text/html" in content_type or data.lstrip().startswith((b"<html", b"<!DOCTYPE")):
                raise RuntimeError("返回了网页而非图片")
            suffix = (
                ".webp"
                if "webp" in content_type or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")
                else ".png"
                if "png" in content_type or data.startswith(b"\x89PNG")
                else ".jpg"
            )
            destination = asset_dir / f"{prefix}_{index:02d}{suffix}"
            destination.write_bytes(data)
            saved.append(destination.name)
        except Exception as exc:
            errors.append(f"图片{index}: {exc}")
            destination.unlink(missing_ok=True)
    return saved, errors


def run_asr(video_path: Path, model: str) -> tuple[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    command = [str(PYTHON), str(ASR_SCRIPT), str(video_path), model]
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", "转写超过 30 分钟，已停止等待"
    except Exception as exc:
        return "", f"无法启动 asr_video.py: {exc}"
    transcript_path = video_path.with_name(video_path.stem + "_transcript.txt")
    if result.returncode != 0:
        detail = clean_inline(result.stderr or result.stdout, "未知错误")[-600:]
        return "", f"asr_video.py 退出码 {result.returncode}: {detail}"
    if not transcript_path.exists():
        return "", "asr_video.py 已结束，但未生成 transcript 文件"
    transcript = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
    if not transcript:
        return "", "转写文件为空（视频可能无可识别语音）"
    return transcript, ""


def fetch_dy_api_info(page: Any, detail_url: str) -> dict[str, Any]:
    """复用浏览器已签名的详情 API 请求地址，补齐文案、互动和视频源。"""
    match = re.search(r"(?:/video/|[?&]modal_id=)(\d+)", detail_url)
    aweme_id = match.group(1) if match else ""
    try:
        api_urls = page.run_js(
            "return performance.getEntriesByType('resource').map(e => e.name)"
            ".filter(u => u.includes('/aweme/v1/web/aweme/detail/'));"
        ) or []
    except Exception:
        api_urls = []
    api_url = next((u for u in reversed(api_urls) if not aweme_id or f"aweme_id={aweme_id}" in u), "")
    if not api_url:
        return {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
        "Referer": detail_url,
        "Accept": "application/json, text/plain, */*",
    }
    cookie = browser_cookie_header(page)
    if cookie:
        headers["Cookie"] = cookie
    try:
        with urlopen(Request(api_url, headers=headers), timeout=30) as response:
            payload = json.load(response)
    except Exception as exc:
        print(f"  [详情 API 降级] {exc}")
        return {}
    aweme = payload.get("aweme_detail") if isinstance(payload, dict) else None
    if not isinstance(aweme, dict):
        return {}
    author = aweme.get("author") or {}
    stats = aweme.get("statistics") or {}
    video = aweme.get("video") or {}
    urls: list[str] = []
    for key in ("play_addr", "play_addr_h264", "download_addr"):
        value = video.get(key) or {}
        urls.extend(value.get("url_list") or [])
    image_urls: list[str] = []
    image_items = aweme.get("images") or (aweme.get("image_album") or {}).get("images") or []
    for image in image_items:
        if not isinstance(image, dict):
            continue
        candidates = image.get("url_list") or image.get("download_url_list") or []
        if candidates:
            image_urls.append(candidates[0])
    desc = clean_block(aweme.get("desc"))
    return {
        "title": desc.splitlines()[0][:180] if desc else "",
        "desc": desc,
        "author": author.get("nickname") or author.get("unique_id") or "",
        "time": aweme.get("create_time") or "",
        "likes": stats.get("digg_count"),
        "comments": stats.get("comment_count"),
        "shares": stats.get("share_count"),
        "collects": stats.get("collect_count"),
        "videoUrls": urls,
        "imageUrls": image_urls,
        "awemeType": aweme.get("aweme_type"),
    }


def capture_dy(
    page: Any,
    url: str,
    video_path: Path,
    model: str,
    asset_dir: Path,
    asset_prefix: str,
) -> Capture:
    page.get(url)
    time.sleep(6)
    try:
        info = parse_json(page.run_js(DY_DETAIL_JS))
    except Exception:
        info = {}
    api_info = fetch_dy_api_info(page, url)
    for key, value in api_info.items():
        if value not in (None, "", []):
            info[key] = value
    title = clean_inline(info.get("title"), "抖音内容")
    body = clean_block(info.get("desc"))
    if not body:
        body = element_text(
            page,
            ["css:[data-e2e='video-desc']", "css:[class*='video-info-detail']", "h1"],
            timeout=2,
        )
    if not body:
        visible = clean_block(page_text(page))
        body = visible[:8000] if visible else "（未提取到页面文案）"
    author = clean_inline(info.get("author"))
    published = format_published(info.get("time"))
    counts = []
    for label, key in [("赞", "likes"), ("藏", "collects"), ("评", "comments"), ("分享", "shares")]:
        if info.get(key) is not None:
            counts.append(f"{info[key]}{label}")
    interactions = " / ".join(counts) or "未获取"
    comments = extract_comments(page)

    image_urls = [normalize_video_candidate(value) for value in info.get("imageUrls", [])]
    candidates = [] if image_urls else video_candidates(page, info)
    transcript = ""
    video_note = ""
    media_note = ""
    image_refs: list[str] = []
    content_type = "图文" if image_urls and not candidates else "视频" if candidates else "未知"
    if content_type == "视频":
        downloaded, reason = download_video(page, candidates, video_path, url)
        if downloaded:
            print(f"  [视频] 已下载 {downloaded.name} ({downloaded.stat().st_size / 1024 / 1024:.1f} MB)")
            transcript, asr_reason = run_asr(downloaded, model)
            if transcript:
                print("  [转写] 成功")
            else:
                reason = asr_reason
                print(f"  [转写降级] {reason}")
        else:
            print(f"  [视频降级] {reason}")
        if not transcript:
            video_note = f"仅保存页面文案；{reason or '未生成转写'}"
    elif content_type == "图文":
        saved, image_errors = download_images(page, image_urls, asset_dir, asset_prefix, url)
        image_refs = [f"_assets/{name}" for name in saved]
        print(f"  [图文] 已保存 {len(saved)} / {len(image_urls[:12])} 张图片")
        if image_errors:
            media_note = "; ".join(image_errors[-3:])
    else:
        media_note = "详情 API 未返回视频或图片地址，仅保存文案与评论"
        print(f"  [媒体降级] {media_note}")
    return Capture(
        title=title,
        author=author,
        published_at=published,
        body=body,
        interactions=interactions,
        comments=comments,
        transcript=transcript,
        video_note=video_note,
        content_type=content_type,
        images=image_refs,
        media_note=media_note,
    )


def format_markdown(capture: Capture, platform: str, url: str, error: str = "") -> str:
    captured_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        f"# {clean_inline(capture.title, '采集失败记录')}",
        "",
        f"- 平台：{PLATFORM_LABEL[platform]}",
        f"- 内容类型：{clean_inline(capture.content_type)}",
        f"- 链接：{url}",
        f"- 采集时间：{captured_at}",
        f"- 发布时间：{clean_inline(capture.published_at)}",
        f"- 作者：{clean_inline(capture.author)}",
        f"- 互动数：{clean_inline(capture.interactions)}",
        "",
        "## 正文",
        "",
        clean_block(capture.body) or "（未提取到正文）",
        "",
    ]
    if capture.images:
        lines.extend(["## 图片", ""])
        for index, image_path in enumerate(capture.images, start=1):
            lines.extend([f"![图片 {index}]({image_path})", ""])
    lines.extend([f"## 评论（前 {MAX_COMMENTS} 条）", ""])
    if capture.comments:
        for comment in capture.comments[:MAX_COMMENTS]:
            lines.extend([f"- {comment.replace(chr(10), '<br>')}", ""])
    else:
        lines.extend(["（未提取到评论或该内容暂无评论）", ""])
    if capture.transcript or capture.video_note:
        lines.extend(["## 视频转写", "", capture.transcript or f"（{capture.video_note}）", ""])
    if capture.media_note:
        lines.extend(["## 媒体说明", "", capture.media_note, ""])
    if error:
        lines.extend(["## 采集异常", "", error, ""])
    return "\n".join(lines).rstrip() + "\n"


def next_sequence(output_dir: Path, date_token: str, platform_label: str, keyword_file: str) -> int:
    prefix = f"{date_token}_{platform_label}_{keyword_file}_"
    maximum = 0
    for path in output_dir.glob(prefix + "*.md"):
        match = re.search(r"_(\d+)\.md$", path.name)
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum + 1


def write_summary(
    output_dir: Path,
    keyword: str,
    platform: str,
    started: datetime,
    successes: list[tuple[str, str, Path]],
    failures: list[tuple[str, str]],
) -> Path:
    summary_path = output_dir / "_汇总.md"
    header = f"# {keyword} 采集汇总\n"
    if not summary_path.exists():
        summary_path.write_text(header, encoding="utf-8")
    run_title = started.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "",
        f"## {run_title} · {PLATFORM_LABEL[platform]}",
        "",
        f"- 成功：{len(successes)}",
        f"- 失败：{len(failures)}",
        "",
        "### 当日采集清单",
        "",
    ]
    for title, url, path in successes:
        lines.append(f"- [[{path.stem}|{clean_inline(title, path.stem)}]] · [原链接]({url})")
    if not successes:
        lines.append("- （本次无成功条目）")
    if failures:
        lines.extend(["", "### 失败记录", ""])
        for url, reason in failures:
            lines.append(f"- [原链接]({url})：{clean_inline(reason)}")
    with summary_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return summary_path


def collect_search_links(page: Any, platform: str, keyword: str, maximum: int) -> list[tuple[str, str]]:
    if platform == "xhs":
        cmd_search_xhs(page, keyword)
        # 搜索卡片的 /search_result/<id>?xsec_token=... 才能可靠进入详情；
        # read_social 的 /explore/ 链接仍用于兼容旧版页面。
        links = (
            extract_links(page, "/search_result/")
            or extract_links(page, "/explore/")
            or extract_links(page, "/discovery/")
        )
        return unique_links(links, "https://www.xiaohongshu.com", maximum)
    cmd_search_dy(page, keyword)
    links = extract_links(page, "/video/")
    normalized = unique_links(links, "https://www.douyin.com", maximum)
    if normalized:
        return normalized
    return collect_dy_card_links(page, maximum)


def collect_dy_card_links(page: Any, maximum: int) -> list[tuple[str, str]]:
    """兼容新版抖音：搜索卡片无 a[href]，点击后 URL 才出现 modal_id。"""
    search_url = str(getattr(page, "url", "") or "")
    output: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    index = 0
    while len(output) < maximum:
        try:
            if index:
                page.get(search_url)
                time.sleep(4)
            cards = page.eles(".search-result-card", timeout=5)
            if index >= len(cards):
                break
            card_text = clean_block(cards[index].text or "")
            title = next((line for line in card_text.splitlines() if len(line.strip()) >= 6), "抖音视频")
            cards[index].click()
            time.sleep(2)
            detail_url = str(getattr(page, "url", "") or "")
            modal = re.search(r"[?&]modal_id=(\d+)", detail_url)
            if not modal:
                print(f"[链接兼容] 第 {index + 1} 张卡片点击后未出现 modal_id，跳过")
                index += 1
                continue
            if modal.group(1) in seen_ids:
                print(f"[链接兼容] 卡片 {index + 1} 与已有内容重复，跳过")
                index += 1
                continue
            seen_ids.add(modal.group(1))
            output.append((title[:100], f"https://www.douyin.com/video/{modal.group(1)}"))
            print(f"[链接兼容] 卡片 {index + 1} → modal_id={modal.group(1)}")
        except Exception as exc:
            print(f"[链接兼容] 第 {index + 1} 张卡片读取失败：{exc}")
        index += 1
    return output


def derive_video_keyword(url: str) -> str:
    match = re.search(r"/video/(\d+)", url)
    if match:
        return "dyvideo_" + match.group(1)[-12:]
    host = urlparse(url).netloc.split(":")[0] or "链接"
    return "dyvideo_" + safe_component(host, "链接", 24)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小红书/抖音搜索、详情、转写、Markdown 入库流水线")
    parser.add_argument("platform", choices=("xhs", "dy", "dyvideo"), help="xhs / dy / dyvideo")
    parser.add_argument("query", help="搜索关键词；dyvideo 模式下填写视频链接")
    parser.add_argument("--max", type=int, default=20, dest="maximum", help="最多处理条数，默认 20")
    parser.add_argument("--asr-model", default="small", choices=("tiny", "base", "small", "medium"), help="faster-whisper 模型，默认 small")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.maximum < 1:
        print("[参数错误] --max 必须大于 0")
        return 2
    if not check_debug_port():
        return 1
    try:
        page = connect()
    except SystemExit as exc:
        return int(exc.code or 1)
    except Exception as exc:
        print(f"[连接失败] 请先双击 start_browser.bat：{exc}")
        return 1

    try:
        login_gate(page, args.platform)
    except (EOFError, KeyboardInterrupt):
        print("\n[已取消] 尚未确认登录，未开始采集。")
        return 130

    started = datetime.now().astimezone()
    keyword = args.query if args.platform != "dyvideo" else derive_video_keyword(args.query)
    keyword_dir = safe_component(keyword, "未命名关键词", 80)
    keyword_file = safe_component(keyword, "未命名关键词", 40)
    output_dir = OUTPUT_ROOT / keyword_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    date_token = started.strftime("%Y%m%d")
    platform_label = PLATFORM_LABEL[args.platform]
    sequence = next_sequence(output_dir, date_token, platform_label, keyword_file)

    if args.platform == "dyvideo":
        links = [("抖音单视频", args.query)]
    else:
        try:
            links = collect_search_links(page, args.platform, args.query, args.maximum)
        except Exception as exc:
            print(f"[搜索失败] {exc}")
            links = []
    if not links:
        print("[未发现链接] 可能未登录、遇到风控，或页面结构已变化。")

    successes: list[tuple[str, str, Path]] = []
    failures: list[tuple[str, str]] = []
    total = min(len(links), args.maximum)
    for offset, (search_title, url) in enumerate(links[: args.maximum]):
        current_sequence = sequence + offset
        filename = f"{date_token}_{platform_label}_{keyword_file}_{current_sequence:02d}.md"
        md_path = output_dir / filename
        print(f"\n[{offset + 1}/{total}] {url}")
        try:
            if args.platform == "xhs":
                video_name = f"{date_token}_小红书_{keyword_file}_{current_sequence:02d}.mp4"
                capture = capture_xhs(page, url, VIDEO_DIR / video_name, args.asr_model)
            else:
                video_name = f"{date_token}_抖音_{keyword_file}_{current_sequence:02d}.mp4"
                capture = capture_dy(
                    page,
                    url,
                    VIDEO_DIR / video_name,
                    args.asr_model,
                    output_dir / "_assets",
                    f"{date_token}_抖音_{keyword_file}_{current_sequence:02d}",
                )
            if not capture.title and search_title:
                capture.title = search_title
            md_path.write_text(format_markdown(capture, args.platform, url), encoding="utf-8", newline="\n")
            successes.append((capture.title, url, md_path))
            print(f"  [已写入] {md_path}")
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            failures.append((url, reason))
            failed_capture = Capture(title=search_title or "采集失败记录")
            try:
                md_path.write_text(
                    format_markdown(failed_capture, args.platform, url, error=reason),
                    encoding="utf-8",
                    newline="\n",
                )
                print(f"  [失败已存档] {md_path}")
            except Exception as write_exc:
                print(f"  [失败且无法写存档] {reason}; 写入错误: {write_exc}")
            print(f"  [单条失败，继续] {reason}")
        finally:
            if offset + 1 < total:
                delay = random.uniform(2, 4)
                print(f"  [防反爬等待] {delay:.1f} 秒")
                time.sleep(delay)

    try:
        summary_path = write_summary(output_dir, keyword, args.platform, started, successes, failures)
        summary_text = str(summary_path)
    except Exception as exc:
        summary_text = f"写入失败：{type(exc).__name__}: {exc}"
    elapsed = max(0.0, (datetime.now().astimezone() - started).total_seconds())
    print("\n" + "=" * 68)
    print(f"完成：成功 {len(successes)} 篇 / 失败 {len(failures)} 条 / 耗时 {elapsed:.1f} 秒")
    print(f"输出目录：{output_dir}")
    print(f"汇总文件：{summary_text}")
    return 0 if links else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[已取消] 用户中断。")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\n[流程异常] {type(exc).__name__}: {exc}")
        raise SystemExit(1)
