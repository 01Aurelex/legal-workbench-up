# -*- coding: utf-8 -*-
import http.client, json, uuid
c = http.client.HTTPConnection("127.0.0.1", 8765, timeout=180)
c.request("GET", "/api/bootstrap")
tok = json.loads(c.getresponse().read())["token"]
c.request("GET", "/api/media/caps", headers={"X-Auth-Token": tok})
caps = json.loads(c.getresponse().read())["caps"]
print("STT cap:", caps["stt"])
data = open("tests/sample_zh.wav", "rb").read()
bd = "----b" + uuid.uuid4().hex
part = f'--{bd}\r\nContent-Disposition: form-data; name="file"; filename="sample_zh.wav"\r\nContent-Type: audio/wav\r\n\r\n'
body = part.encode() + data + f"\r\n--{bd}--\r\n".encode()
c.request("POST", "/api/media/stt", body=body,
          headers={"X-Auth-Token": tok, "Content-Type": f"multipart/form-data; boundary={bd}"})
d = json.loads(c.getresponse().read())
print("STT ok:", d.get("ok"), "engine:", d.get("engine"))
print("TEXT:", d.get("text"))
