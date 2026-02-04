
import requests
import time

class ManboTTS:
    def __init__(self):
        self.api_url = "https://api.milorapart.top/apis/mbAIsc"

    def generate_speech(self, text: str) -> bytes:
        """
        Calls the Manbo TTS API and returns the audio content as bytes.
        API URL: https://api.milorapart.top/apis/mbAIsc?text=...
        Response: JSON { "code": 200, "url": "..." }
        """
        try:
            # 1. Get the audio URL
            params = {"text": text}
            print(f"[ManboTTS] Requesting TTS for: {text[:10]}...")
            
            # Add a small delay to avoid rate limiting if calling in a loop
            time.sleep(0.5) 
            
            resp = requests.get(self.api_url, params=params, timeout=10)
            resp.raise_for_status()
            
            data = resp.json()
            if data.get("code") != 200:
                print(f"[ManboTTS] API Error: {data}")
                return None
                
            audio_url = data.get("url")
            if not audio_url:
                print("[ManboTTS] No audio URL in response.")
                return None
                
            print(f"[ManboTTS] Downloading audio from: {audio_url}")
            
            # 2. Download the audio file
            audio_resp = requests.get(audio_url, timeout=30)
            audio_resp.raise_for_status()
            
            return audio_resp.content
            
        except Exception as e:
            print(f"[ManboTTS] Error: {e}")
            return None

if __name__ == "__main__":
    tts = ManboTTS()
    audio = tts.generate_speech("你好，这是一个测试。")
    if audio:
        with open("test_manbo.mp3", "wb") as f:
            f.write(audio)
        print("Saved test_manbo.mp3")
