import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# pip install pydub
from pydub import AudioSegment
from utils.manbo_tts import ManboTTS

import random
import glob

# -------------------------
# Config
# -------------------------
@dataclass
class Config:
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    
    # 【画面优化】目标分辨率 720x1280 (9:16), 60fps
    out_w: int = 720
    out_h: int = 1280
    fps: int = 60
    
    sr: int = 48000
    # Increase duration to cover longer scripts (will be cut by -shortest later)
    duration_sec: int = 60 
    
    bgm_path: str = "assets/bgm.mp3"
    ass_tpl_path: str = "templates/subtitle.ass.tpl"
    work_dir: str = "output/_work"

    # 【安全】从环境变量读取 Key
    use_zhipu_tts: bool = False # Disable Zhipu
    use_manbo_tts: bool = True  # Enable Manbo
    zhipu_api_key: str = os.getenv("ZHIPU_API_KEY", "") 
    zhipu_voice_id: str = "tongtong" 
    zhipu_ref_audio: str = None 

    # 画面动效开关
    enable_zoompan: bool = True
    # 钩子文案
    hook_text: str = "3秒学会跑刀！"
    
    # 语音语速 (1.0 = normal, 1.2 = 20% faster)
    audio_speed: float = 1.2


CFG = Config()
tts_client = None


# -------------------------
# Utils
# -------------------------
def run(cmd: List[str]) -> None:
    print("RUN:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def ensure_dir(p: str) -> None:
    Path(p).mkdir(parents=True, exist_ok=True)


def ffprobe_duration(video_path: str) -> float:
    cmd = [
        CFG.ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    try:
        out = subprocess.check_output(cmd).decode().strip()
        return float(out)
    except Exception as e:
        print(f"Warning: Could not get duration for {video_path}: {e}")
        return 0.0


def sec_to_ass_time(t: float) -> str:
    if t < 0: t = 0
    cs = int(round((t - int(t)) * 100))
    s = int(t) % 60
    m = (int(t) // 60) % 60
    h = int(t) // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def split_sentences(text: str) -> List[str]:
    text = text.strip()
    if not text: return []
    parts = re.split(r"(?<=[。！？!?…])\s*", text)
    parts = [p.strip() for p in parts if p.strip()]
    out = []
    for p in parts:
        if len(p) <= 18:
            out.append(p)
        else:
            segs = re.split(r"[，,、]\s*", p)
            buf = ""
            for s in segs:
                if not s: continue
                if len(buf) + len(s) <= 18:
                    buf = (buf + "，" + s) if buf else s
                else:
                    if buf: out.append(buf)
                    buf = s
            if buf: out.append(buf)
    return out


def highlight_keywords(line: str, keywords: List[str]) -> str:
    for kw in keywords:
        if kw and kw in line:
            line = line.replace(kw, r"{\rEmph}" + kw + r"{\rDefault}")
    return line


# -------------------------
# Diagnostics (New)
# -------------------------
def check_audio_streams(video_path: str):
    """【自检1】检查文件是否包含音频流"""
    print(f"\n[Check] Inspecting streams in {video_path}...")
    cmd = [CFG.ffprobe, "-v", "error", "-show_streams", video_path]
    try:
        res = subprocess.check_output(cmd).decode()
        if "codec_type=audio" in res:
            print("  -> PASS: Audio stream detected.")
        else:
            print("  -> FAIL: No audio stream found!")
    except Exception as e:
        print(f"  -> FAIL: ffprobe error: {e}")


def check_wav_volume(wav_path: str):
    """【自检2】检查音频文件的响度，确保不是静音"""
    print(f"\n[Check] Analyzing volume of {wav_path}...")
    # volumedetect filter
    cmd = [
        CFG.ffmpeg, "-i", wav_path,
        "-af", "volumedetect",
        "-f", "null", "/dev/null"
    ]
    # ffmpeg prints filter stats to stderr
    res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    log = res.stderr.decode()
    
    # Extract mean_volume and max_volume
    mean_vol = re.search(r"mean_volume:\s*([-.\d]+)\s*dB", log)
    max_vol = re.search(r"max_volume:\s*([-.\d]+)\s*dB", log)
    
    if mean_vol and max_vol:
        mv = float(mean_vol.group(1))
        mx = float(max_vol.group(1))
        print(f"  -> Stats: Mean={mv}dB, Max={mx}dB")
        if mx < -50:
            print("  -> WARNING: File seems nearly silent!")
        else:
            print("  -> PASS: Volume levels look normal.")
    else:
        print("  -> WARNING: Could not parse volumedetect output.")


def process_audio_speed(in_file: str, out_file: str, speed: float) -> bool:
    """
    Use ffmpeg atempo filter to change speed without pitch shift.
    Supports speed from 0.5 to 2.0 (single pass).
    """
    if abs(speed - 1.0) < 0.01:
        return False
        
    print(f"  -> Applying audio speed {speed}x...")
    cmd = [
        CFG.ffmpeg, "-y",
        "-i", in_file,
        "-filter:a", f"atempo={speed}",
        "-vn", 
        out_file
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"  -> Speed change failed: {e}")
        return False

# -------------------------
# TTS Logic
# -------------------------
def tts_generate_wav(text: str, out_wav: str) -> None:
    """
    【修复】
    1. 接收 TTS API 返回的二进制数据
    2. 存为临时文件
    3. 用 pydub 转码为标准 PCM wav (48k, 16bit)
    """
    global tts_client
    
    # 尝试使用 Manbo TTS
    if CFG.use_manbo_tts:
        try:
            if tts_client is None:
                tts_client = ManboTTS()
                
            print(f"TTS Generating (Manbo): {text[:10]}...")
            audio_data = tts_client.generate_speech(text)
            
            if audio_data:
                print(f"  -> Received {len(audio_data)} bytes from Manbo.")
                
                # Manbo returns mp3
                tmp_audio = out_wav + ".tmp.mp3" # Save as mp3 explicitly
                with open(tmp_audio, "wb") as f:
                    f.write(audio_data)
                
                # Apply speed change if needed
                processed_audio = tmp_audio
                if CFG.audio_speed != 1.0:
                    speed_out = out_wav + ".speed.wav"
                    if process_audio_speed(tmp_audio, speed_out, CFG.audio_speed):
                        processed_audio = speed_out
                
                # Try to read with pydub (auto detect)
                try:
                    # print("  -> Attempting to read audio with pydub (autodetect)...")
                    seg = AudioSegment.from_file(processed_audio)
                except Exception as e_auto:
                    print(f"  -> Autodetect failed: {e_auto}. Trying format='mp3'...")
                    try:
                        seg = AudioSegment.from_file(processed_audio, format="mp3")
                    except Exception as e_mp3:
                        print(f"  -> MP3 read failed: {e_mp3}. Fallback...")
                        raise
                
                seg = seg.set_frame_rate(CFG.sr).set_channels(1) 
                seg.export(out_wav, format="wav")
                
                # Cleanup
                for f in [tmp_audio, out_wav + ".speed.wav"]:
                    try: os.remove(f) 
                    except: pass
                return
                
        except Exception as e:
            print(f"ERROR: Manbo TTS failed ({e}). Fallback to silent.")

    # 尝试使用智谱 TTS (Legacy)
    if CFG.use_zhipu_tts:
        # ... (Zhipu logic kept but disabled by config) ...
        pass

    # Fallback
    print("TTS Fallback: Generating loud tone for debugging.")
    est_ms = int((len(text) * 0.25 + 0.5) * 1000)
    # 生成一个 440Hz 的正弦波 (beep) 替代静音，确保能听到
    from pydub.generators import Sine
    audio = Sine(440).to_audio_segment(duration=est_ms).apply_gain(-10)
    audio = audio.set_frame_rate(CFG.sr).set_channels(1)
    audio.export(out_wav, format="wav")


def build_voice_and_timings(sentences: List[str], keywords: List[str], work: str) -> Tuple[str, List[Tuple[float, float, str]]]:
    ensure_dir(work)
    segments = []
    timings = []
    t = 0.0
    
    for i, s in enumerate(sentences):
        tmp = os.path.join(work, f"tts_{i:03d}.wav")
        tts_generate_wav(s, tmp)
        
        # 验证生成的wav是否有效
        try:
            seg = AudioSegment.from_file(tmp)
        except:
            # 再次fallback防止崩
            seg = AudioSegment.silent(duration=1000, frame_rate=CFG.sr)
            
        dur = seg.duration_seconds
        sub = highlight_keywords(s, keywords)
        timings.append((t, t + dur, sub))
        t += dur
        
        # 句间停顿 0.15s
        pause = AudioSegment.silent(duration=150, frame_rate=CFG.sr)
        segments.append(seg + pause)
        t += 0.15

    if not segments:
        voice = AudioSegment.silent(duration=1000, frame_rate=CFG.sr)
    else:
        voice = sum(segments)

    # 统一输出格式：48k, Stereo
    voice_wav = os.path.join(work, "voice.wav")
    voice = voice.set_frame_rate(CFG.sr).set_channels(2)
    voice.export(voice_wav, format="wav")
    
    # 【自检】
    check_wav_volume(voice_wav)
    
    return voice_wav, timings


def render_ass(timings: List[Tuple[float, float, str]], ass_tpl_path: str, out_ass: str) -> None:
    tpl = Path(ass_tpl_path).read_text(encoding="utf-8")
    events = []
    for (st, ed, text) in timings:
        start = sec_to_ass_time(st)
        end = sec_to_ass_time(ed)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    content = tpl.format(events="\n".join(events))
    Path(out_ass).write_text(content, encoding="utf-8")


# -------------------------
# FFmpeg pipeline
# -------------------------
def make_vertical_clip(in_videos: List[str], out_video: str) -> None:
    """
    【画面优化】
    1. 随机拼接多个视频
    2. 缩放+裁切到 720x1280
    3. FPS=60
    4. Zoompan 动态效果
    5. Drawtext 钩子文案
    """
    
    # 1. 构造 Filter Complex 链
    # 对每个输入进行 scale+crop 归一化
    # 然后 concat
    
    inputs = []
    filter_parts = []
    
    for i, v in enumerate(in_videos):
        inputs.extend(["-i", v])
        # scale+crop logic for each input
        # 注意：[0:v] 引用第0个输入
        # filter: [0:v]scale=...[v0]
        
        filter_scale_crop = (
            f"[{i}:v]"
            f"scale=if(gte(iw/ih\,{CFG.out_w}/{CFG.out_h})\,-2\,{CFG.out_w}):"
            f"if(gte(iw/ih\,{CFG.out_w}/{CFG.out_h})\,{CFG.out_h}\,-2),"
            f"crop={CFG.out_w}:{CFG.out_h}[v{i}];"
        )
        filter_parts.append(filter_scale_crop)
    
    # Concat part: [v0][v1]...concat=n=N:v=1:a=0[v_concat]
    concat_inputs = "".join([f"[v{i}]" for i in range(len(in_videos))])
    filter_parts.append(f"{concat_inputs}concat=n={len(in_videos)}:v=1:a=0[v_concat];")
    
    # 2. 动态效果 (Zoompan) on [v_concat]
    zoompan_in = "[v_concat]"
    
    if CFG.enable_zoompan:
        z_expr = "min(zoom+0.0005,1.1)" 
        y_expr = "ih/2-(ih/zoom/2) - (ih*0.05)"
        x_expr = "iw/2-(iw/zoom/2)"
        
        filter_parts.append(
            f"{zoompan_in}zoompan=z='{z_expr}':d=1:"
            f"x='{x_expr}':y='{y_expr}':s={CFG.out_w}x{CFG.out_h}:fps={CFG.fps}[v_zoom];"
        )
        final_v = "[v_zoom]"
    else:
        final_v = zoompan_in

    # 3. 钩子文案 (Drawtext)
    if CFG.hook_text:
        txt = CFG.hook_text
        dt = (
            f"{final_v}drawtext=font='Microsoft YaHei':text='{txt}':"
            "fontcolor=yellow:fontsize=60:borderw=3:bordercolor=black:"
            "x=(w-text_w)/2:y=150:"
            "enable='between(t,0,2.5)'[v_final]"
        )
        filter_parts.append(dt)
        final_v = "[v_final]"
    
    # 组合整个 complex filter
    filter_complex = "".join(filter_parts)
    # Remove trailing semicolon if any (though usually fine)
    
    # 注意：如果视频总时长小于 duration_sec，stream_loop -1 对 filter complex 无效
    # concat 后的流无法简单 loop。
    # 简单策略：如果总时长不够，我们在 inputs 里重复添加视频直到够？
    # 或者，利用 -stream_loop -1 在输入层？
    # -stream_loop -1 -i v1 -stream_loop -1 -i v2 ...
    # 这样 concat 会无限长？ffmpeg 可能会卡死或只取最长？
    # 稳妥策略：在 Python 层重复列表，确保至少有 3-4 个视频循环，或者足够长
    
    # 重复列表以确保足够覆盖 duration_sec (60s)
    # 假设每个视频至少 5s，重复 15 次足够
    # 但为了避免 filter string 过长，我们先不做无限 loop，
    # 而是假设输入文件夹里的素材够多，或者循环 selected_videos 列表几次
    
    # Re-construct inputs with loop in mind
    # Better: just multiply the list in python
    pass # Implementation below handles this by re-calling logic if needed?
    # No, let's just make sure in_videos list is long enough.
    
    vf_chain = filter_complex

    cmd = [CFG.ffmpeg, "-y"]
    
    # Apply stream_loop to each input? 
    # No, that makes them infinite. Concat of infinite streams never finishes first segment.
    # We must NOT loop inputs indefinitely if using concat.
    
    # We will loop the output using -stream_loop on the result? No.
    # We will just generate a long enough video.
    
    cmd.extend(inputs)
    cmd.extend([
        "-t", str(CFG.duration_sec),
        "-filter_complex", vf_chain,
        "-map", final_v, # Map the final output pad
        "-an", 
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "veryfast",
        "-crf", "18", 
        out_video
    ])
    
    run(cmd)

def make_vertical_clip_wrapper(videos: List[str], out_video: str):
    # Ensure we have enough clips for 60s
    # Simple heuristic: repeat the list 5 times
    long_list = videos * 5
    # Limit to reasonable number to avoid huge command line (e.g. max 20 clips)
    if len(long_list) > 20:
        long_list = long_list[:20]
        
    make_vertical_clip(long_list, out_video)


def mux_with_voice_bgm_and_subtitles(vertical_video: str, voice_wav: str, ass_path: str, out_mp4: str) -> None:
    """
    【声音优化】
    1. 侧链压缩 (Ducking): Voice 出现时压低 BGM
    2. 响度标准化 (Loudnorm): 目标 -14 LUFS (适合短视频)
    3. 确保 Voice 响度足够
    """
    
    # 转义路径供 filter 使用
    ass_path_esc = ass_path.replace("\\", "/").replace(":", "\\:")

    # 滤镜链设计：
    # [1:a] (Voice) -> pre-amp -> [voice_clean] -> split -> [voice_ctrl][voice_out]
    # [2:a] (BGM) -> volume down -> [bgm_in]
    # [bgm_in][voice_ctrl] sidechaincompress -> [bgm_ducked]
    # [bgm_ducked][voice_out] amix -> [mix_raw]
    # [mix_raw] loudnorm -> [aout]
    
    af = (
        # 1. Voice 处理：稍微放大确保清晰，转 48k
        "[1:a]volume=1.5,aresample=48000,asplit[voice_ctrl][voice_out];"
        
        # 2. BGM 处理：默认 0.2 倍音量，避免抢戏
        "[2:a]volume=0.2,aresample=48000[bgm_in];"
        
        # 3. Ducking: 阈值 0.1, 压缩比 10, 快速触发(5ms) 慢恢复(200ms)
        "[bgm_in][voice_ctrl]sidechaincompress=threshold=0.05:ratio=10:attack=5:release=200[bgm_ducked];"
        
        # 4. Mix: 混合
        "[bgm_ducked][voice_out]amix=inputs=2:duration=longest[mix_raw];"
        
        # 5. Loudness Normalization (EBU R128)
        # I=-14 (Youtube/TikTok standard-ish), TP=-1 (True Peak), LRA=7 (Dynamic Range)
        "[mix_raw]loudnorm=I=-14:TP=-1.0:LRA=7[aout]"
    )

    run([
        CFG.ffmpeg, "-y",
        "-i", vertical_video,
        "-i", voice_wav,
        "-i", CFG.bgm_path,
        "-filter_complex", af,
        "-map", "0:v:0",
        "-map", "[aout]",
        # 烧录字幕
        "-vf", f"ass='{ass_path_esc}'",
        
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        
        "-c:a", "aac",
        "-b:a", "256k", # 提高音频码率
        
        "-shortest",
        out_mp4
    ])
    
    # 【自检】
    check_audio_streams(out_mp4)


def main():
    # 检查 Key
    if not CFG.zhipu_api_key and CFG.use_zhipu_tts:
        print("WARNING: ZHIPU_API_KEY is not set in environment variables!")
        print("Set it via: $env:ZHIPU_API_KEY='your_key' (PowerShell) or set in code.")
    
    ensure_dir("output")
    ensure_dir(CFG.work_dir)

    in_video_dir = "E:\\jj\\input"
    out_vertical = os.path.join(CFG.work_dir, "vertical.mp4")
    out_ass = os.path.join(CFG.work_dir, "sub.ass")
    out_final = "output/final.mp4"

    # Find video files
    video_exts = ("*.mp4", "*.mov", "*.mkv")
    all_videos = []
    for ext in video_exts:
        all_videos.extend(glob.glob(os.path.join(in_video_dir, ext)))
    
    if not all_videos:
        print(f"Error: No video files found in {in_video_dir}")
        return

    # Randomly select multiple videos to form a montage
    random.shuffle(all_videos)
    # Just use all of them in random order (loop logic handles duration)
    selected_videos = all_videos 
    print(f"Selected {len(selected_videos)} videos for montage: {[os.path.basename(v) for v in selected_videos]}")

    # Load script from E:\jj\文案 directory (random text file)
    script_dir = r"E:\jj\文案"
    script_path = None
    
    if os.path.isdir(script_dir):
        txt_files = glob.glob(os.path.join(script_dir, "*.txt"))
        if txt_files:
            script_path = random.choice(txt_files)
            print(f"Selected script file: {script_path}")
            
            # Use filename (without extension) as hook text
            filename = os.path.splitext(os.path.basename(script_path))[0]
            # Simple heuristic: if filename is long, it might be the hook
            CFG.hook_text = filename
            print(f"Set Hook Text from filename: {CFG.hook_text}")
    
    sentences = []
    if script_path and os.path.exists(script_path):
        print(f"Loading script from {script_path}...")
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                # Filter empty lines and strip whitespace
                lines = [line.strip() for line in f if line.strip()]
                
            # If first line looks like a title/hook (short), we could use it too?
            # User said "用...文案和标题". Assuming filename is title is safer if file content is just body.
            # But let's check if first line is very short and matches filename?
            # For now, just load all lines as script body.
            sentences = lines
            print(f"Loaded {len(sentences)} lines of text.")
        except Exception as e:
            print(f"Error reading script file: {e}")
            
    # Fallback if file not found or empty
    if not sentences:
        print("Using default fallback script.")
        script = "再也不怕出货带不出来了！3×3老板首选。现在特价998，速通！"
        sentences = split_sentences(script)
        keywords = ["3×3", "998", "速通", "出货"]
    else:
        # Keywords for the new text
        keywords = ["押金", "跑刀", "老板", "筛人机制", "风险"]

    print("--- Step 1: Video Processing (Zoompan + 60fps) ---")
    make_vertical_clip_wrapper(selected_videos, out_vertical)

    print("--- Step 2: TTS Generation (with MP3 fix) ---")
    # sentences is already prepared above
    voice_wav, timings = build_voice_and_timings(sentences, keywords, CFG.work_dir)

    print("--- Step 3: Subtitle Rendering ---")
    render_ass(timings, CFG.ass_tpl_path, out_ass)

    print("--- Step 4: Final Mixing (Ducking + Loudnorm) ---")
    mux_with_voice_bgm_and_subtitles(out_vertical, voice_wav, out_ass, out_final)

    print("\nALL DONE:", out_final)


if __name__ == "__main__":
    main()
