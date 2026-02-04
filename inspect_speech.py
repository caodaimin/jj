from zhipuai import ZhipuAI
import inspect

client = ZhipuAI(api_key="test")
print(inspect.signature(client.audio.speech))
