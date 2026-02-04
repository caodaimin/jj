
import os
import time
from dotenv import load_dotenv
from utils.zhipu_tts import ZhipuTTS
import subprocess

load_dotenv()
api_key = os.getenv("ZHIPU_API_KEY")

def main():
    if not api_key:
        print("API Key not found!")
        return

    tts = ZhipuTTS(api_key=api_key)
    
    # 1. Use existing valid reference audio (skip generation to avoid 1214 error)
    print("Using existing reference audio...")
    ref_audio_path = "assets/my_voice_mono.wav"
    
    if not os.path.exists(ref_audio_path):
        print(f"Error: Reference audio file not found at {ref_audio_path}")
        return

    # 2. Clone Voice
    print(f"Cloning voice from {ref_audio_path}...")
    # Assuming the audio content is the standard ref text, or try a generic one if unsure.
    # If the file was generated with "这是一个标准的参考音频...", use that.
    # If it was "这是一个测试音频", use that.
    # Let's try the longer one first as it was the intent of this script.
    # ref_text_likely = "这是一个标准的参考音频，用于测试音色复刻功能。"
    # Try the shorter one which matches the default used in previous attempts
    ref_text_likely = "这是一个测试音频。"
    voice_id = tts.create_voice_from_file(ref_audio_path, voice_text=ref_text_likely)
    
    if not voice_id:
        print("Failed to clone voice.")
        return
        
    print(f"Voice cloned successfully! Voice ID: {voice_id}")
    
    # 3. Speak
    print("Generating speech with cloned voice...")
    try:
        audio = tts.generate_speech("恭喜你，音色复刻成功了！", voice=voice_id)
        if audio:
            out_file = "final_clone_test.mp3"
            with open(out_file, "wb") as f:
                f.write(audio)
            print(f"Success! Saved to {out_file}")
        else:
            print("No audio data received.")
    except Exception as e:
        print(f"Generation failed: {e}")

if __name__ == "__main__":
    main()
