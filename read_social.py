# -*- coding: utf-8 -*-
"""
SocialReader - 用已登录的Chrome读取小红书/抖音内容
用法:
  python read_social.py search xhs 关键词     # 搜小红书(标题/作者/日期/赞数)
  python read_social.py search dy 关键词      # 搜抖音
  python read_social.py read current          # 读当前打开的页面(妹妹手动点开后用)
  python read_social.py read <链接>           # 直接打开链接读取(部分站会重定向)
"""
import sys
import time
import re
import json
from urllib.parse import quote
from DrissionPage import ChromiumPage

sys.stdout.reconfigure(encoding='utf-8')

PORT = '127.0.0.1:9333'
MAX_TEXT = 8000


def connect():
    try:
        return ChromiumPage(addr_or_opts=PORT)
    except Exception as e:
        print('[连接失败] 请先双击 start_browser.bat 启动调试浏览器，再运行本工具。')
        print(f'详情: {e}')
        sys.exit(1)


def page_text(page):
    """取页面可见文本（DrissionPage 4.x: body 元素的 text）"""
    try:
        body = page.ele('tag:body', timeout=3)
        return body.text if body else ''
    except Exception:
        return ''


def tidy(text):
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


def strip_tail(lines):
    """去掉页面底部的版权/备案噪音行"""
    cut = len(lines)
    for i, l in enumerate(lines):
        if '沪ICP备' in l or '京ICP备' in l or '行吟信息' in l or '©' in l:
            cut = i
            break
    return lines[:cut]


def extract_links(page, pattern):
    links = []
    for a in page.eles('tag:a', timeout=5):
        try:
            href = a.attr('href') or ''
            txt = (a.text or '').strip()
            if pattern in href:
                links.append((txt[:80], href))
        except Exception:
            pass
    out = []
    seen = set()
    for t, h in links:
        if h not in seen:
            seen.add(h)
            out.append((t, h))
    return out


def cmd_search_xhs(page, kw):
    url = 'https://www.xiaohongshu.com/search_result?keyword=' + quote(kw)
    page.get(url)
    time.sleep(5)
    print(f'== 小红书 搜索「{kw}」 ==')
    body = tidy(page_text(page))
    idx = body.find('筛选')
    zone = body[idx + 2:] if idx >= 0 else body
    lines = [l.strip() for l in zone.split('\n') if l.strip()]
    lines = strip_tail(lines)
    if lines:
        print('\n'.join(lines[:60]))
        print(f'...(共 {len(lines)} 行文本)')
    else:
        print('[搜索区为空，可能未登录或被风控]')
    links = extract_links(page, '/explore/')
    if not links:
        links = extract_links(page, '/discovery/')
    print(f'-- 笔记链接 {len(links)} 条（前5条）:')
    for t, h in links[:5]:
        print(f'   {h[:100]}')


def cmd_search_dy(page, kw):
    url = 'https://www.douyin.com/search/' + quote(kw)
    page.get(url)
    time.sleep(7)
    print(f'== 抖音 搜索「{kw}」 ==')
    body = tidy(page_text(page))
    # 结果区大概在"搜索"之后
    idx = body.find('搜索')
    zone = body[idx + 2:] if idx >= 0 else body
    lines = [l.strip() for l in zone.split('\n') if l.strip()]
    lines = strip_tail(lines)
    if lines and len(lines) > 3:
        print('\n'.join(lines[:60]))
        print(f'...(共 {len(lines)} 行文本)')
    else:
        print('[搜索区为空 → 大概率没登录抖音，请在浏览器里登录 douyin.com]')
    vids = extract_links(page, '/video/')
    print(f'-- 视频链接 {len(vids)} 条（前5条）:')
    for t, h in vids[:5]:
        print(f'   {h[:100]}')


def cmd_read_current(page):
    title = (page.title or '').strip()
    url = page.url or ''
    print(f'== 当前页: {title} ==')
    print(f'== URL: {url} ==')
    if is_xhs_detail(page):
        if xhs_note_detail(page):
            return
    body = tidy(page_text(page))
    print(body[:MAX_TEXT])
    if len(body) > MAX_TEXT:
        print(f'\n...[截断，全文共 {len(body)} 字符]')


def is_xhs_detail(page):
    """判断当前页是不是小红书笔记详情页"""
    url = page.url or ''
    return 'xiaohongshu.com' in url and any(k in url for k in ('/explore/', '/discovery/', '/notes/'))


def xhs_note_detail(page):
    """小红书笔记详情：等正文渲染，优先 __INITIAL_STATE__（权威），.desc 兜底。

    小红书详情页正文是异步渲染的，直接抓 body 文本只会拿到导航+推荐流，
    必须等 .note-container 出现，或从 window.__INITIAL_STATE__ 直接取数据。
    """
    # 1. 等笔记容器出现（最多 ~15s）
    for _ in range(15):
        try:
            c = page.ele('.note-container', timeout=1.5)
            if c and len((c.text or '').strip()) > 30:
                break
        except Exception:
            pass
        time.sleep(1)
    # 2. 权威数据：__INITIAL_STATE__.note.noteDetailMap（正文/作者/互动数据）
    try:
        raw = page.run_js(JS_INITIAL_STATE)
        info = json.loads(raw) if raw else None
    except Exception:
        info = None
    if info and info.get('title'):
        print(f"== 标题: {info['title'][:100]}")
        if info.get('author'):
            print(f"== 作者: {info['author'][:80]}")
        print(f"== 数据: {info['likes']}赞 / {info['collects']}藏 / {info['comments']}评 / {info['shares']}分享")
        print('\n== 正文 ==')
        print(info['desc'][:MAX_TEXT])
        if len(info['desc']) > MAX_TEXT:
            print(f"\n...[截断，全文共 {len(info['desc'])} 字符]")
        return True
    # 3. 兜底：.desc 元素
    try:
        desc = page.ele('.desc', timeout=3)
        if desc and (desc.text or '').strip():
            print('== 正文（.desc 兜底）==')
            print((desc.text or '').strip()[:MAX_TEXT])
            return True
    except Exception:
        pass
    return False


JS_INITIAL_STATE = """const st = window.__INITIAL_STATE__;
const map = (st && st.note && st.note.noteDetailMap) || {};
const id = Object.keys(map)[0];
const d = map[id];
if (!d || !d.note) return '';
const n = d.note;
const u = n.user || {};
const c = n.interactInfo || {};
return JSON.stringify({
  title: n.title || '',
  desc: (n.desc || '').slice(0, 20000),
  author: (u.nickname || '') + (u.desc ? ' | ' + u.desc : ''),
  likes: c.likedCount || 0,
  collects: c.collectedCount || 0,
  comments: c.commentCount || 0,
  shares: c.sharedCount || 0,
  type: n.type || '',
  time: n.time || ''
});"""


def cmd_read_url(page, url):
    page.get(url)
    time.sleep(6)
    title = (page.title or '').strip()
    if '生活兴趣社区' in title or '小红书的首页' in title:
        print(f'== 链接: {url} ==')
        print('[小红书详情页直连被重定向到首页(反自动化)。]')
        print('[解决办法: 请你在浏览器里手动点开这篇笔记，然后告诉我，我用 read current 读。]')
        return
    print(f'== 链接: {url} ==')
    if is_xhs_detail(page):
        if xhs_note_detail(page):
            return
    body = tidy(page_text(page))
    print(f'== 标题: {title} ==')
    print(body[:MAX_TEXT])
    if len(body) > MAX_TEXT:
        print(f'\n...[截断，全文共 {len(body)} 字符]')


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    page = connect()
    if args[0] == 'search' and len(args) >= 3:
        if args[1].lower() == 'xhs':
            cmd_search_xhs(page, args[2])
        elif args[1].lower() == 'dy':
            cmd_search_dy(page, args[2])
        else:
            print('平台仅支持 xhs / dy')
    elif args[0] == 'read' and len(args) >= 2:
        if args[1] == 'current':
            cmd_read_current(page)
        else:
            cmd_read_url(page, args[1])
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
