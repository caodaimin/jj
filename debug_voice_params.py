
import os
from zhipuai import ZhipuAI
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ZHIPU_API_KEY")
client = ZhipuAI(api_key=api_key)

voices_to_test = ["neon"] # Just test one likely voice
formats_to_test = ["wav", "mp3", "aac", "flac", "pcm", "opus", "ogg"]
model = "glm-4-voice"

print(f"Testing formats for model {model}...")

for fmt in formats_to_test:
    print(f"Testing format: {fmt}")
    try:
        response = client.audio.speech(
            model=model,
            input="你好，这是一个测试。",
            voice="neon",
            encode_format=fmt
        )
        print(f"SUCCESS with format: {fmt}")
        break
    except Exception as e:
        print(f"FAILED with format {fmt}: {e}")
