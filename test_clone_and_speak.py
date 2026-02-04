
import os
import time
from dotenv import load_dotenv
from utils.zhipu_tts import ZhipuTTS

load_dotenv()
api_key = os.getenv("ZHIPU_API_KEY")

def main():
    if not api_key:
        print("API Key not found!")
        return

    tts = ZhipuTTS(api_key=api_key)
    ref_audio = "assets/my_voice_mono.wav"
    
    if not os.path.exists(ref_audio):
        print(f"Reference audio not found: {ref_audio}")
        return

    print(f"Cloning voice from {ref_audio}...")
    voice_id = tts.create_voice_from_file(ref_audio)
    
    if not voice_id:
        print("Failed to clone voice.")
        return
        
    print(f"Voice cloned successfully! Voice ID: {voice_id}")
    
    print("Generating speech with cloned voice...")
    try:
        # Note: generate_speech now uses encode_format=None
        audio = tts.generate_speech("这是一个测试音频，用于验证音色复刻功能。", voice=voice_id)
        
        if audio:
            out_file = "test_clone_output.mp3"
            with open(out_file, "wb") as f:
                f.write(audio)
            print(f"Audio generated and saved to {out_file}")
            print(f"Size: {len(audio)} bytes")
        else:
            print("No audio data received.")
    except Exception as e:
        print(f"Generation failed: {e}")

if __name__ == "__main__":
    main()
