# SocialReader 内容采集流水线

一个面向 Windows 的本地内容采集工具：连接你自己登录的 Chrome 调试浏览器，把小红书/抖音内容整理成可搜索的 Markdown，并用本地 faster-whisper 免费转写视频。

支持：

- 小红书图文：标题、作者、正文、互动、前 10 条评论。
- 小红书视频：在上述内容基础上下载视频并转写；失败时保留正文与评论。
- 抖音视频：文案、互动、评论、视频下载与转写。
- 抖音图文：文案、互动、评论和图片下载，图片以 Obsidian 相对路径嵌入 Markdown。
- 单条抖音链接，以及搜索关键词批量采集。
- 本地 Web 控制台和命令行两种入口。

## 推荐：Web 操作界面

1. 双击项目目录里的 `start_web.bat`。
2. 浏览器会自动打开 `http://127.0.0.1:8787`。
3. 如果右上角显示“9333 未连接”，点击页面里的“启动调试浏览器”。
4. 选择平台、填写关键词和数量，点击“开始采集”。
5. 调试浏览器打开登录页后完成登录，再回到网页点击“我已登录，继续”。

网页会实时显示采集日志、成功/失败数量和转写进度；下方“最近采集”可以直接预览 Markdown，也可以一键打开输出文件夹。Web 服务只监听本机 `127.0.0.1`，不会开放到局域网或互联网。

## 安装

要求：Windows、Chrome、Python 3.10–3.12。

```powershell
git clone https://github.com/waxymoon/SocialReader.git
cd SocialReader
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

默认输出到 `D:\ObsidianVault\采集\内容流水线`。如果你的 Obsidian 仓库不在这里，可在启动前设置：

```powershell
$env:SOCIALREADER_OUTPUT_ROOT = 'E:\你的仓库\采集\内容流水线'
python web_capture.py
```

视频与转写文件默认放在项目的 `videos` 目录，也可通过 `SOCIALREADER_MEDIA_ROOT` 修改。

## 运行前准备

1. 双击项目目录里的 `start_browser.bat`，确认调试浏览器已启动（端口 `127.0.0.1:9333`）。
2. 每次启动流水线后，程序会先打开对应网站并显示登录提示。请只在这一个调试浏览器窗口中扫码/登录，完成后回到终端按回车。
3. 普通浏览器与调试浏览器的登录态互不相通。

## 用法

在 Git Bash 中：

```bash
cd /d/SocialReader
env -u PYTHONPATH D:/Python312/python.exe pipeline_capture.py xhs "AI 工具" --max 3
env -u PYTHONPATH D:/Python312/python.exe pipeline_capture.py dy "AI 工具" --max 3
env -u PYTHONPATH D:/Python312/python.exe pipeline_capture.py dyvideo "https://www.douyin.com/video/视频ID"
```

在 PowerShell 中，等价做法是只为本次进程移除 `PYTHONPATH`：

```powershell
$savedPythonPath = $env:PYTHONPATH
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
python .\pipeline_capture.py xhs 'AI 工具' --max 3
$env:PYTHONPATH = $savedPythonPath
```

可选参数：

- `--max N`：最多处理 N 条，默认 20。
- `--asr-model tiny|base|small|medium`：faster-whisper 模型，默认 `small`。

## 输出

每篇内容写入：

```text
D:\ObsidianVault\采集\内容流水线\<关键词>\YYYYMMDD_平台_关键词_序号.md
```

同目录的 `_汇总.md` 会按每次运行追加采集清单。视频暂存于项目的 `videos\`，转写文本由 `asr_video.py` 写在视频旁边；抖音图文图片保存在关键词目录的 `_assets\`。

每条详情之间会随机等待 2–4 秒。单条遇到滑块、超时、视频下载或转写失败时，程序会记录原因并继续；抖音下载/转写失败时仍会输出页面文案和原链接。

## 常见问题

- 显示“未检测到 127.0.0.1:9333”：先双击 `start_browser.bat`。
- 搜不到链接或正文为空：在调试浏览器确认已登录，并检查是否出现验证码/滑块。
- 视频只有文案：视频源可能是临时地址、需要额外校验，或视频没有可识别语音；Markdown 会写明降级原因。
- 网站 DOM 和状态对象会变化；如果连续多条为空，应先用 `read_social.py read current` 确认当前页面是否仍可读。

## 隐私与使用边界

- 不需要任何付费 API Key；Whisper 模型在本机运行。
- `profile\` 保存 Chrome 登录态和 Cookie，已被 `.gitignore` 排除，切勿上传或分享。
- `videos\`、模型、转写、采集结果和 QA 截图默认不进入 Git。
- 请只采集你有权访问和保存的内容，遵守平台规则、著作权和个人信息保护要求；不要用于高频抓取或绕过验证码。

## License

MIT
