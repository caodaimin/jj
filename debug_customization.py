
import os
import time
from zhipuai import ZhipuAI
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ZHIPU_API_KEY")
client = ZhipuAI(api_key=api_key)

voice_name = "my_test_voice"
unique_name = f"{voice_name}_{int(time.time())}"
ref_audio_path = "assets/my_voice_mono.wav"
voice_text = "这是一个测试音频。" # Short text matching the likely content

if not os.path.exists(ref_audio_path):
    print(f"File not found: {ref_audio_path}")
    exit(1)

print(f"Cloning voice using SDK from {ref_audio_path}...")
try:
    with open(ref_audio_path, "rb") as f:
        response = client.audio.customization(
            model="glm-tts-clone",
            input="音色复刻测试。",
            voice_text=voice_text,
            voice_data=(os.path.basename(ref_audio_path), f, "application/octet-stream"),
            extra_body={
                "voice_name": unique_name
            }
        )
    print(f"Response: {response}")
except Exception as e:
    print(f"SDK Customization failed: {e}")
