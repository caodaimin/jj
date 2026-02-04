
import os
from dotenv import load_dotenv
from utils.zhipu_tts import ZhipuTTS

load_dotenv()
api_key = os.getenv("ZHIPU_API_KEY")
tts = ZhipuTTS(api_key=api_key)

formats = ["mp3", "wav", "pcm", "aac", "flac", "m4a", "ogg", None]

for fmt in formats:
    print(f"Testing format: {fmt}")
    try:
        # We manually call client.audio.speech to override encode_format
        response = tts.client.audio.speech(
            model="glm-4-voice",
            input="test",
            voice="default",
            encode_format=fmt
        )
        print(f"SUCCESS with {fmt}")
        break
    except Exception as e:
        print(f"FAILED with {fmt}: {e}")
