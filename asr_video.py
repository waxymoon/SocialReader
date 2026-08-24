# -*- coding: utf-8 -*-
"""小红书视频语音转文字：faster-whisper。用法:
env -u PYTHONPATH HF_ENDPOINT=https://hf-mirror.com "D:/Python312/python.exe" asr_video.py <mp4> [模型]
模型: tiny/base/small/medium, 默认 small（中文够用）
"""
import sys, os, time
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

mp4 = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent / 'videos' / 'sample.mp4')
model_size = sys.argv[2] if len(sys.argv) > 2 else 'small'

from faster_whisper import WhisperModel

t0 = time.time()
print(f'加载模型 {model_size}...', flush=True)
model = WhisperModel(model_size, device='cpu', compute_type='int8')
print(f'模型就绪 ({time.time()-t0:.0f}s)', flush=True)

t0 = time.time()
segments, info = model.transcribe(mp4, language='zh', beam_size=5, vad_filter=True)
print(f'音频信息: {info.language} {info.duration:.1f}s', flush=True)

out = []
for seg in segments:
    line = f'[{seg.start:06.1f}s → {seg.end:06.1f}s] {seg.text.strip()}'
    print(line, flush=True)
    out.append(line)

txt = '\n'.join(out)
dest = os.path.splitext(mp4)[0] + '_transcript.txt'
open(dest, 'w', encoding='utf-8').write(txt)
print(f'\n== 完成 ({time.time()-t0:.0f}s)，共 {len(out)} 句 → {dest}')
