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
    
    # Default to Vertical 9:16
    out_w: int = 720
    out_h: int = 1280
    fps: int = 60
    
    sr: int = 48000
    duration_sec: int = 60 
    
    bgm_path: str = "assets/bgm.mp3"
    # We will generate ASS header dynamically or use template
    ass_tpl_path: str = "templates/subtitle.ass.tpl" 
    work_dir: str = "output/_work"

    # API Keys
    use_zhipu_tts: bool = False
    use_manbo_tts: bool = True
    zhipu_api_key: str = os.getenv("ZHIPU_API_KEY", "") 
    zhipu_voice_id: str = "tongtong" 
    zhipu_ref_audio: str = None 

    enable_zoompan: bool = True
    hook_text: str = "3秒学会跑刀！"
    
    audio_speed: float = 1.2
    
    # New: Input directories
    in_video_dir: str = "E:\\jj\\input"
    script_dir: str = "E:\\jj\\文案"


# -------------------------
# Utils
# -------------------------
def run(cmd: List[str]) -> None:
    print("RUN:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def ensure_dir(p: str) -> None:
    Path(p).mkdir(parents=True, exist_ok=True)


def ffprobe_duration(video_path: str, config: Config) -> float:
    cmd = [
        config.ffprobe, "-v", "error",
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
def check_audio_streams(video_path: str, config: Config):
    """【自检1】检查文件是否包含音频流"""
    print(f"\n[Check] Inspecting streams in {video_path}...")
    cmd = [config.ffprobe, "-v", "error", "-show_streams", video_path]
    try:
        res = subprocess.check_output(cmd).decode()
        if "codec_type=audio" in res:
            print("  -> PASS: Audio stream detected.")
        else:
            print("  -> FAIL: No audio stream found!")
    except Exception as e:
        print(f"  -> FAIL: ffprobe error: {e}")


def check_wav_volume(wav_path: str, config: Config):
    """【自检2】检查音频文件的响度，确保不是静音"""
    print(f"\n[Check] Analyzing volume of {wav_path}...")
    # volumedetect filter
    cmd = [
        config.ffmpeg, "-i", wav_path,
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


def process_audio_speed(in_file: str, out_file: str, speed: float, config: Config) -> bool:
    """
    Use ffmpeg atempo filter to change speed without pitch shift.
    Supports speed from 0.5 to 2.0 (single pass).
    """
    if abs(speed - 1.0) < 0.01:
        return False
        
    print(f"  -> Applying audio speed {speed}x...")
    cmd = [
        config.ffmpeg, "-y",
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
tts_client = None

def tts_generate_wav(text: str, out_wav: str, config: Config) -> None:
    """
    【修复】
    1. 接收 TTS API 返回的二进制数据
    2. 存为临时文件
    3. 用 pydub 转码为标准 PCM wav (48k, 16bit)
    """
    global tts_client
    
    # 尝试使用 Manbo TTS
    if config.use_manbo_tts:
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
                if config.audio_speed != 1.0:
                    speed_out = out_wav + ".speed.wav"
                    if process_audio_speed(tmp_audio, speed_out, config.audio_speed, config):
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
                
                seg = seg.set_frame_rate(config.sr).set_channels(1) 
                seg.export(out_wav, format="wav")
                
                # Cleanup
                for f in [tmp_audio, out_wav + ".speed.wav"]:
                    try: os.remove(f) 
                    except: pass
                return
                
        except Exception as e:
            print(f"ERROR: Manbo TTS failed ({e}). Fallback to silent.")

    # 尝试使用智谱 TTS (Legacy)
    if config.use_zhipu_tts:
        # ... (Zhipu logic kept but disabled by config) ...
        pass

    # Fallback
    print("TTS Fallback: Generating loud tone for debugging.")
    est_ms = int((len(text) * 0.25 + 0.5) * 1000)
    # 生成一个 440Hz 的正弦波 (beep) 替代静音，确保能听到
    from pydub.generators import Sine
    audio = Sine(440).to_audio_segment(duration=est_ms).apply_gain(-10)
    audio = audio.set_frame_rate(config.sr).set_channels(1)
    audio.export(out_wav, format="wav")


def build_voice_and_timings(sentences: List[str], keywords: List[str], work: str, config: Config) -> Tuple[str, List[Tuple[float, float, str]]]:
    ensure_dir(work)
    segments = []
    timings = []
    t = 0.0
    
    for i, s in enumerate(sentences):
        tmp = os.path.join(work, f"tts_{i:03d}.wav")
        tts_generate_wav(s, tmp, config)
        
        # 验证生成的wav是否有效
        try:
            seg = AudioSegment.from_file(tmp)
        except:
            # 再次fallback防止崩
            seg = AudioSegment.silent(duration=1000, frame_rate=config.sr)
            
        dur = seg.duration_seconds
        sub = highlight_keywords(s, keywords)
        timings.append((t, t + dur, sub))
        t += dur
        
        # 句间停顿 0.15s
        pause = AudioSegment.silent(duration=150, frame_rate=config.sr)
        segments.append(seg + pause)
        t += 0.15

    if not segments:
        voice = AudioSegment.silent(duration=1000, frame_rate=config.sr)
    else:
        voice = sum(segments)

    # 统一输出格式：48k, Stereo
    voice_wav = os.path.join(work, "voice.wav")
    voice = voice.set_frame_rate(config.sr).set_channels(2)
    voice.export(voice_wav, format="wav")
    
    # 【自检】
    check_wav_volume(voice_wav, config)
    
    return voice_wav, timings


def render_ass(timings: List[Tuple[float, float, str]], ass_tpl_path: str, out_ass: str, config: Config) -> None:
    # If using dynamic template based on resolution
    # But for now, let's assume the template file is still used, 
    # OR we can inject resolution specific margins here.
    
    # Check if using file or generating dynamic
    # Let's try to read the file first
    try:
        tpl = Path(ass_tpl_path).read_text(encoding="utf-8")
    except:
        # Fallback to default string if file not found
        # 400 margin for vertical (1280h), maybe 50 for horizontal (720h)
        margin_v = 400 if config.out_h > config.out_w else 50
        tpl = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.out_w}
PlayResY: {config.out_h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,50,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,2,20,20,{margin_v},1
Style: Emph,Microsoft YaHei,60,&H0000FFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,2,20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{{events}}
"""
    
    # If we read from file, we might want to override PlayRes and MarginV?
    # For now, let's rely on the file if it exists, but user might want horizontal support.
    # If the file is hardcoded to 720x1280, it will break horizontal layout.
    # So we should probably dynamically adjust it or use two templates.
    # Let's dynamically patch it if it's the default template.
    if "PlayResY: 1280" in tpl and config.out_w > config.out_h:
        # Switching to Horizontal
        tpl = tpl.replace("PlayResX: 720", f"PlayResX: {config.out_w}")
        tpl = tpl.replace("PlayResY: 1280", f"PlayResY: {config.out_h}")
        # Adjust margin V from 400 to 50
        tpl = tpl.replace(",400,1", ",50,1")
    
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
def make_clip(in_videos: List[str], out_video: str, config: Config) -> None:
    """
    【画面优化】
    1. 随机拼接多个视频
    2. 缩放+裁切到 config.out_w x config.out_h
    3. FPS=config.fps
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
        
        # Scale logic: cover the target aspect ratio
        # if (iw/ih > out_w/out_h) -> scale height to out_h, width auto (-2)
        # else -> scale width to out_w, height auto (-2)
        # Then crop to out_w:out_h
        
        target_ar = config.out_w / config.out_h
        
        filter_scale_crop = (
            f"[{i}:v]"
            f"scale=if(gte(iw/ih\,{target_ar})\,-2\,{config.out_w}):"
            f"if(gte(iw/ih\,{target_ar})\,{config.out_h}\,-2),"
            f"crop={config.out_w}:{config.out_h}[v{i}];"
        )
        filter_parts.append(filter_scale_crop)
    
    # Concat part: [v0][v1]...concat=n=N:v=1:a=0[v_concat]
    concat_inputs = "".join([f"[v{i}]" for i in range(len(in_videos))])
    filter_parts.append(f"{concat_inputs}concat=n={len(in_videos)}:v=1:a=0[v_concat];")
    
    # 2. 动态效果 (Zoompan) on [v_concat]
    zoompan_in = "[v_concat]"
    
    if config.enable_zoompan:
        z_expr = "min(zoom+0.0005,1.1)" 
        y_expr = "ih/2-(ih/zoom/2) - (ih*0.05)"
        x_expr = "iw/2-(iw/zoom/2)"
        
        filter_parts.append(
            f"{zoompan_in}zoompan=z='{z_expr}':d=1:"
            f"x='{x_expr}':y='{y_expr}':s={config.out_w}x{config.out_h}:fps={config.fps}[v_zoom];"
        )
        final_v = "[v_zoom]"
    else:
        final_v = zoompan_in

    # 3. 钩子文案 (Drawtext)
    if config.hook_text:
        txt = config.hook_text
        # Adjust Y position for horizontal? 
        # For vertical (1280h), y=150 is good (top area).
        # For horizontal (720h), y=150 is also okay (top area).
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
    
    vf_chain = filter_complex

    cmd = [config.ffmpeg, "-y"]
    
    cmd.extend(inputs)
    cmd.extend([
        "-t", str(config.duration_sec),
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

def make_clip_wrapper(videos: List[str], out_video: str, config: Config):
    # Ensure we have enough clips for duration
    # Simple heuristic: repeat the list 5 times
    long_list = videos * 5
    # Limit to reasonable number to avoid huge command line (e.g. max 20 clips)
    if len(long_list) > 20:
        long_list = long_list[:20]
        
    make_clip(long_list, out_video, config)


def mux_with_voice_bgm_and_subtitles(vertical_video: str, voice_wav: str, ass_path: str, out_mp4: str, config: Config) -> None:
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
        config.ffmpeg, "-y",
        "-i", vertical_video,
        "-i", voice_wav,
        "-i", config.bgm_path,
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
    check_audio_streams(out_mp4, config)


def main():
    cfg = Config()
    
    # 检查 Key
    if not cfg.zhipu_api_key and cfg.use_zhipu_tts:
        print("WARNING: ZHIPU_API_KEY is not set in environment variables!")
        print("Set it via: $env:ZHIPU_API_KEY='your_key' (PowerShell) or set in code.")
    
    ensure_dir("output")
    ensure_dir(cfg.work_dir)

    out_clip = os.path.join(cfg.work_dir, "clip.mp4")
    out_ass = os.path.join(cfg.work_dir, "sub.ass")
    out_final = "output/final.mp4"

    # Find video files
    video_exts = ("*.mp4", "*.mov", "*.mkv")
    all_videos = []
    for ext in video_exts:
        all_videos.extend(glob.glob(os.path.join(cfg.in_video_dir, ext)))
    
    if not all_videos:
        print(f"Error: No video files found in {cfg.in_video_dir}")
        return

    # Randomly select multiple videos to form a montage
    random.shuffle(all_videos)
    # Just use all of them in random order (loop logic handles duration)
    selected_videos = all_videos 
    print(f"Selected {len(selected_videos)} videos for montage: {[os.path.basename(v) for v in selected_videos]}")

    # Load script from script_dir (random text file)
    script_path = None
    
    if os.path.isdir(cfg.script_dir):
        txt_files = glob.glob(os.path.join(cfg.script_dir, "*.txt"))
        if txt_files:
            script_path = random.choice(txt_files)
            print(f"Selected script file: {script_path}")
            
            # Use filename (without extension) as hook text
            filename = os.path.splitext(os.path.basename(script_path))[0]
            cfg.hook_text = filename
            print(f"Set Hook Text from filename: {cfg.hook_text}")
    
    sentences = []
    if script_path and os.path.exists(script_path):
        print(f"Loading script from {script_path}...")
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                # Filter empty lines and strip whitespace
                lines = [line.strip() for line in f if line.strip()]
                
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
    make_clip_wrapper(selected_videos, out_clip, cfg)

    print("--- Step 2: TTS Generation (with MP3 fix) ---")
    # sentences is already prepared above
    voice_wav, timings = build_voice_and_timings(sentences, keywords, cfg.work_dir, cfg)

    print("--- Step 3: Subtitle Rendering ---")
    render_ass(timings, cfg.ass_tpl_path, out_ass, cfg)

    print("--- Step 4: Final Mixing (Ducking + Loudnorm) ---")
    mux_with_voice_bgm_and_subtitles(out_clip, voice_wav, out_ass, out_final, cfg)

    print("\nALL DONE:", out_final)


if __name__ == "__main__":
    main()
