import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import sys
import threading
import os
import glob
import random
import time

# Import core logic from jj.py
# We need to add the current directory to sys.path if not present
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from jj import Config, make_clip_wrapper, build_voice_and_timings, render_ass, mux_with_voice_bgm_and_subtitles, ensure_dir, split_sentences

class RedirectText(object):
    def __init__(self, text_ctrl):
        self.output = text_ctrl

    def write(self, string):
        self.output.insert(tk.END, string)
        self.output.see(tk.END)

    def flush(self):
        pass

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("全自动视频生成工具 (Video Generator)")
        self.root.geometry("700x800")
        
        self.style = ttk.Style()
        self.style.configure("TButton", padding=6)
        self.style.configure("TLabel", padding=5)
        
        # Default Config
        self.cfg = Config()
        
        self.create_widgets()
        
        # Redirect stdout/stderr
        self.redir = RedirectText(self.log_area)
        sys.stdout = self.redir
        sys.stderr = self.redir
        
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- Section 1: Orientation & Basic Settings ---
        settings_frame = ttk.LabelFrame(main_frame, text="基础设置 (Basic Settings)", padding="10")
        settings_frame.pack(fill=tk.X, pady=5)
        
        # Orientation
        ttk.Label(settings_frame, text="视频比例 (Aspect Ratio):").grid(row=0, column=0, sticky=tk.W)
        self.orientation_var = tk.StringVar(value="vertical")
        ttk.Radiobutton(settings_frame, text="竖屏 (9:16) - 抖音/TikTok", variable=self.orientation_var, value="vertical").grid(row=0, column=1, sticky=tk.W)
        ttk.Radiobutton(settings_frame, text="横屏 (16:9) - B站/Youtube", variable=self.orientation_var, value="horizontal").grid(row=0, column=2, sticky=tk.W)
        
        # Audio Speed
        ttk.Label(settings_frame, text="语速 (Audio Speed):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.speed_var = tk.DoubleVar(value=1.2)
        speed_spin = ttk.Spinbox(settings_frame, from_=0.5, to=2.0, increment=0.1, textvariable=self.speed_var, width=5)
        speed_spin.grid(row=1, column=1, sticky=tk.W, pady=5)
        ttk.Label(settings_frame, text="(1.0 = 原速)").grid(row=1, column=2, sticky=tk.W)

        # --- Section 2: Paths ---
        paths_frame = ttk.LabelFrame(main_frame, text="资源路径 (Resources)", padding="10")
        paths_frame.pack(fill=tk.X, pady=5)
        
        # Video Input
        ttk.Label(paths_frame, text="视频素材目录:").grid(row=0, column=0, sticky=tk.W)
        self.video_dir_var = tk.StringVar(value=self.cfg.in_video_dir)
        ttk.Entry(paths_frame, textvariable=self.video_dir_var, width=50).grid(row=0, column=1, padx=5)
        ttk.Button(paths_frame, text="浏览...", command=self.browse_video_dir).grid(row=0, column=2)
        
        # Script Dir
        ttk.Label(paths_frame, text="文案目录/文件:").grid(row=1, column=0, sticky=tk.W)
        self.script_dir_var = tk.StringVar(value=self.cfg.script_dir)
        ttk.Entry(paths_frame, textvariable=self.script_dir_var, width=50).grid(row=1, column=1, padx=5)
        ttk.Button(paths_frame, text="浏览...", command=self.browse_script_dir).grid(row=1, column=2)
        
        # BGM File
        ttk.Label(paths_frame, text="背景音乐 (BGM):").grid(row=2, column=0, sticky=tk.W)
        self.bgm_path_var = tk.StringVar(value=self.cfg.bgm_path)
        ttk.Entry(paths_frame, textvariable=self.bgm_path_var, width=50).grid(row=2, column=1, padx=5)
        ttk.Button(paths_frame, text="浏览...", command=self.browse_bgm).grid(row=2, column=2)

        # --- Section 3: Advanced ---
        adv_frame = ttk.LabelFrame(main_frame, text="高级 (Advanced)", padding="10")
        adv_frame.pack(fill=tk.X, pady=5)
        
        self.zoompan_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(adv_frame, text="启用画面动态缩放 (Zoompan)", variable=self.zoompan_var).grid(row=0, column=0, sticky=tk.W)

        # --- Section 4: Actions ---
        btn_frame = ttk.Frame(main_frame, padding="10")
        btn_frame.pack(fill=tk.X, pady=10)
        
        self.run_btn = ttk.Button(btn_frame, text="开始生成 (Start Generation)", command=self.start_thread, width=30)
        self.run_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="退出 (Exit)", command=self.root.quit).pack(side=tk.RIGHT, padx=5)
        
        # --- Section 5: Logs ---
        log_frame = ttk.LabelFrame(main_frame, text="运行日志 (Logs)", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.log_area = scrolledtext.ScrolledText(log_frame, state='normal', height=15)
        self.log_area.pack(fill=tk.BOTH, expand=True)

    def browse_video_dir(self):
        d = filedialog.askdirectory(initialdir=self.video_dir_var.get())
        if d: self.video_dir_var.set(d)

    def browse_script_dir(self):
        d = filedialog.askdirectory(initialdir=self.script_dir_var.get())
        if d: self.script_dir_var.set(d)

    def browse_bgm(self):
        f = filedialog.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav")])
        if f: self.bgm_path_var.set(f)

    def start_thread(self):
        self.run_btn.config(state='disabled')
        t = threading.Thread(target=self.worker)
        t.daemon = True
        t.start()

    def worker(self):
        try:
            print("\n=== Initializing Generation Task ===")
            
            # 1. Update Config from GUI
            cfg = Config()
            
            # Orientation
            if self.orientation_var.get() == "horizontal":
                cfg.out_w = 1280
                cfg.out_h = 720
                print("Mode: Horizontal (16:9)")
            else:
                cfg.out_w = 720
                cfg.out_h = 1280
                print("Mode: Vertical (9:16)")
            
            cfg.audio_speed = self.speed_var.get()
            cfg.in_video_dir = self.video_dir_var.get()
            cfg.script_dir = self.script_dir_var.get()
            cfg.bgm_path = self.bgm_path_var.get()
            cfg.enable_zoompan = self.zoompan_var.get()
            
            # 2. Validation
            if not os.path.exists(cfg.in_video_dir):
                print(f"Error: Video dir not found: {cfg.in_video_dir}")
                return
            
            # 3. Execution Logic (similar to main in jj.py)
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

            # Randomize
            random.shuffle(all_videos)
            selected_videos = all_videos 
            print(f"Selected {len(selected_videos)} videos.")

            # Load Script
            script_path = None
            if os.path.isdir(cfg.script_dir):
                txt_files = glob.glob(os.path.join(cfg.script_dir, "*.txt"))
                if txt_files:
                    script_path = random.choice(txt_files)
                    print(f"Selected script file: {script_path}")
                    filename = os.path.splitext(os.path.basename(script_path))[0]
                    cfg.hook_text = filename
                    print(f"Set Hook Text: {cfg.hook_text}")
            elif os.path.isfile(cfg.script_dir): # If user selected a specific file
                script_path = cfg.script_dir
                print(f"Selected script file: {script_path}")
                filename = os.path.splitext(os.path.basename(script_path))[0]
                cfg.hook_text = filename
            
            sentences = []
            if script_path and os.path.exists(script_path):
                try:
                    with open(script_path, "r", encoding="utf-8") as f:
                        lines = [line.strip() for line in f if line.strip()]
                    sentences = lines
                    print(f"Loaded {len(sentences)} lines of text.")
                except Exception as e:
                    print(f"Error reading script: {e}")
            
            # Fallback
            if not sentences:
                print("Warning: No script found. Using default text.")
                script = "演示文案：这里是默认文案，请选择有效的文案目录！"
                sentences = split_sentences(script)
                cfg.hook_text = "默认演示"
                keywords = ["默认"]
            else:
                keywords = ["押金", "跑刀", "老板", "风险", "速通"] # Generic keywords

            # --- Step 1: Video ---
            print("\n--- Step 1: Video Processing ---")
            make_clip_wrapper(selected_videos, out_clip, cfg)

            # --- Step 2: TTS ---
            print("\n--- Step 2: TTS Generation ---")
            voice_wav, timings = build_voice_and_timings(sentences, keywords, cfg.work_dir, cfg)

            # --- Step 3: Subtitles ---
            print("\n--- Step 3: Subtitle Rendering ---")
            render_ass(timings, cfg.ass_tpl_path, out_ass, cfg)

            # --- Step 4: Mix ---
            print("\n--- Step 4: Final Mixing ---")
            mux_with_voice_bgm_and_subtitles(out_clip, voice_wav, out_ass, out_final, cfg)

            print(f"\nSUCCESS! Video saved to: {os.path.abspath(out_final)}")
            messagebox.showinfo("Success", f"Video generated successfully!\n{out_final}")

        except Exception as e:
            print(f"\nCRITICAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            messagebox.showerror("Error", f"An error occurred:\n{e}")
        finally:
            self.run_btn.config(state='normal')

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
