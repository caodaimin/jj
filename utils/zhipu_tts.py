
from zhipuai import ZhipuAI
import os
import json
import time
import httpx
from zhipuai.core._jwt_token import generate_token

class ZhipuTTS:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = ZhipuAI(api_key=api_key)

    def generate_speech(self, text: str, voice: str = "tongtong", model: str = "glm-tts"):
        """
        Generate speech using standard TTS.
        """
        try:
            # Use glm-tts standard model
            response = self.client.audio.speech(
                model=model,
                input=text,
                voice=voice,
                encode_format=None 
            )
            
            if hasattr(response, 'read'):
                return response.read()
            elif hasattr(response, 'content'):
                return response.content
            else:
                return response
        except Exception as e:
            print(f"Error in generate_speech: {e}")
            raise

    def create_voice_from_file(self, ref_audio_path: str, voice_name: str = "my_voice", voice_text: str = "这是一个测试音频，用于音色复刻。"):
        """
        Create a cloned voice from an audio file.
        Uses the new 'file_id' based flow:
        1. Upload audio to /files (purpose='voice-clone-input')
        2. Call /audio/customization with file_id
        Returns the voice ID.
        """
        if not os.path.exists(ref_audio_path):
            raise FileNotFoundError(f"Reference audio not found: {ref_audio_path}")
            
        try:
            # 1. Upload File
            print(f"[ZhipuTTS] Uploading {ref_audio_path} for voice cloning...")
            file_id = None
            try:
                with open(ref_audio_path, "rb") as f:
                    # purpose='voice-clone-input' is confirmed to work for audio
                    result = self.client.files.create(
                        file=f,
                        purpose="voice-clone-input"
                    )
                file_id = result.id
                print(f"[ZhipuTTS] File uploaded. ID: {file_id}")
            except Exception as e:
                print(f"[ZhipuTTS] Upload failed: {e}")
                # Fallback: try legacy upload in step 2
            
            # 2. Call Customization API
            print(f"[ZhipuTTS] Registering voice '{voice_name}'...")
            
            url = "https://open.bigmodel.cn/api/paas/v4/audio/customization"
            token = generate_token(self.api_key)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            unique_name = f"{voice_name}_{int(time.time())}"
            req_id = f"req_{int(time.time())}"
            
            # Prepare data
            # New API requires file_id, voice_text, input(audition text)
            data = {
                "model": "glm-tts-clone",
                "input": "欢迎使用音色复刻功能，这是您的声音。", 
                "voice_text": voice_text,
                "voice_name": unique_name,
                "request_id": req_id
            }
            if file_id:
                data["file_id"] = file_id

            # Try JSON request first (New Flow)
            if file_id:
                try:
                    print("[ZhipuTTS] Sending JSON request with file_id...")
                    resp = httpx.post(url, headers=headers, json=data, timeout=60.0)
                    if resp.status_code == 200:
                        content = resp.json()
                        if 'voice_id' in content:
                            print(f"[ZhipuTTS] Voice Created! ID: {content['voice_id']}")
                            return content['voice_id']
                        if 'voice' in content:
                             print(f"[ZhipuTTS] Voice Created! ID: {content['voice']}")
                             return content['voice']
                    else:
                        print(f"[ZhipuTTS] JSON request failed: {resp.status_code} {resp.text}")
                except Exception as e:
                    print(f"[ZhipuTTS] JSON request error: {e}")

            # Fallback: Multipart/Form-Data with file upload (Legacy Flow)
            # This is robust if the server doesn't support file_id yet or if we failed to upload
            print("[ZhipuTTS] Falling back to Multipart upload (legacy)...")
            
            # Re-open file
            with open(ref_audio_path, "rb") as f:
                files = {
                    "voice_data": (os.path.basename(ref_audio_path), f, "application/octet-stream")
                }
                # Update data for multipart (remove file_id if present, though it doesn't hurt)
                data_mp = data.copy()
                if "file_id" in data_mp: del data_mp["file_id"]
                
                # Headers: remove Content-Type (httpx sets it)
                headers_mp = headers.copy()
                if "Content-Type" in headers_mp: del headers_mp["Content-Type"]
                
                resp = httpx.post(url, headers=headers_mp, data=data_mp, files=files, timeout=60.0)
                
                if resp.status_code == 200:
                    content = resp.json()
                    vid = content.get('voice_id') or content.get('voice')
                    if vid:
                         print(f"[ZhipuTTS] Voice Created (Legacy)! ID: {vid}")
                         return vid
                
                print(f"[ZhipuTTS] Legacy upload failed: {resp.status_code} {resp.text}")
                return None
            
        except Exception as e:
            print(f"[ZhipuTTS] Clone failed: {e}")
            raise
