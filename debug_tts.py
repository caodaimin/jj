
import os
from dotenv import load_dotenv
from utils.zhipu_tts import ZhipuTTS

# 1. Load env
load_dotenv()
api_key = os.getenv("ZHIPU_API_KEY")

print(f"Loaded API Key: {api_key[:5]}...{api_key[-5:] if api_key else 'None'}")

if not api_key:
    print("ERROR: API Key is empty!")
    exit(1)

# 2. Test Wrapper
print("Testing ZhipuTTS Wrapper...")
tts = ZhipuTTS(api_key=api_key)

try:
    print("Attempting to generate speech via wrapper...")
    audio_data = tts.generate_speech("测试语音合成", voice="default")
    
    if audio_data:
        print(f"Success! Received {len(audio_data)} bytes.")
        with open("debug_output.mp3", "wb") as f:
            f.write(audio_data)
        print("Saved to debug_output.mp3")
    else:
        print("Failed: No data received.")

except Exception as e:
    print("Wrapper Call Failed!")
    print(f"Error details: {e}")
