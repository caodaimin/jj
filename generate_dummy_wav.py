
import wave
import struct
import math

sample_rate = 16000
duration = 3.0 # seconds
frequency = 440.0

obj = wave.open('assets/dummy.wav', 'w')
obj.setnchannels(1) # mono
obj.setsampwidth(2) # 16 bit
obj.setframerate(sample_rate)

data = []
for i in range(int(sample_rate * duration)):
    value = int(32767.0 * math.sin(2.0 * math.pi * frequency * i / sample_rate))
    data.append(struct.pack('<h', value))

obj.writeframes(b''.join(data))
obj.close()
print("Created assets/dummy.wav")
