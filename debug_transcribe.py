
import os
import httpx
from zhipuai.core._jwt_token import generate_token
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ZHIPU_API_KEY")

def transcribe():
    url = "https://open.bigmodel.cn/api/paas/v4/audio/transcriptions"
    token = generate_token(api_key)
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    file_path = "assets/my_voice_mono.wav"
    
    # Try different models if needed
    data = {
        "model": "glm-4-voice", # Or maybe "whisper"?
    }
    
    files = {
        "file": ("test.wav", open(file_path, "rb"), "audio/wav")
    }
    
    print(f"Transcribing {file_path} with raw HTTP...")
    with httpx.Client() as client:
        response = client.post(url, headers=headers, data=data, files=files, timeout=30.0)
        
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")

if __name__ == "__main__":
    transcribe()
