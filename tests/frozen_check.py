# -*- coding: utf-8 -*-
"""免安装冻结包实测：对 dist 中运行的 exe 打接口（127.0.0.1:8765）。"""
import http.client, json, io, uuid, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

c = http.client.HTTPConnection("127.0.0.1", 8765, timeout=60)
c.request("GET", "/api/bootstrap")
tok = json.loads(c.getresponse().read())["token"]
print("1 BOOTSTRAP ok, token len", len(tok))
h = {"X-Auth-Token": tok}

def get(p):
    c.request("GET", p, headers=h); r = c.getresponse(); return r.status, r.read()

def post(p, b):
    c.request("POST", p, body=json.dumps(b, ensure_ascii=False).encode("utf-8"),
              headers={**h, "Content-Type": "application/json"})
    r = c.getresponse(); return r.status, json.loads(r.read())

st, b = get("/")
print("2 FRONTEND", st, b"<!DOCTYPE html" in b)
st, d = get("/api/lawlib/status"); d = json.loads(d)
print("3 LAW chunks", d["chunks"], "files", d["law_files"])
st, d = post("/api/clients", {"name": "测试客户"}); print("4 client", st, d.get("ok"))
st, d = post("/api/cases", {"client": "测试客户", "cause": "买卖合同纠纷",
                            "procedure": "普通程序", "contact_date": "2026-09-02",
                            "filing_date": "2026-09-02"})
cp = d.get("path"); print("5 case", cp)
st, d = post("/api/case/gen-doc", {"case_path": cp, "doc_type": "法律服务合同", "basis": "律师法25条"})
fn = d.get("filename", ""); print("6 GENDOC", fn)
root = Path(__file__).resolve().parents[1] / "dist" / "legal-workbench"
hits = list((root / "data" / "vault" / "文书").rglob(fn))
print("6b docx on disk:", bool(hits), hits[0].name if hits else "")

im = Image.new("RGB", (560, 100), "white"); dr = ImageDraw.Draw(im)
fnt = ImageFont.truetype(r"C:\Windows\Fonts\simsun.ttc", 36)
dr.text((15, 25), "冻结包OCR测试", font=fnt, fill="black")
buf = io.BytesIO(); im.save(buf, format="PNG")
bd = "----b" + uuid.uuid4().hex
body = (f"--{bd}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"t.png\"\r\nContent-Type: image/png\r\n\r\n").encode() \
       + buf.getvalue() + f"\r\n--{bd}--\r\n".encode()
c.request("POST", "/api/media/ocr", body=body,
          headers={"X-Auth-Token": tok, "Content-Type": f"multipart/form-data; boundary={bd}"})
o = json.loads(c.getresponse().read())
print("7 FROZEN OCR", o.get("ok"), o.get("engine"), repr(o.get("text", "")[:40]))

c2 = http.client.HTTPConnection("127.0.0.1", 8765, timeout=30)
c2.request("GET", "/api/lawlib/status")
print("8 NO-TOKEN expect 401 ->", c2.getresponse().status); c2.close()

st, d = get("/api/wechat/status"); d = json.loads(d)
print("9 WECHAT modes note:", d.get("send_mode"), "无需公网" in d.get("note", ""))
print("ALL_FROZEN_CHECKS_DONE")
