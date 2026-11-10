import json
import os
import time
from pathlib import Path
from urllib.request import Request,urlopen


def send(url, report):
    body=json.dumps({k:report[k] for k in ("id","date","status","mode","verified","total","matches")}).encode()
    if not url.startswith("https://"):
        raise ValueError("需要 HTTPS webhook")
    for attempt in range(3):
        try:
            with urlopen(Request(url,body,{"Content-Type":"application/json","Idempotency-Key":report["id"]}),timeout=10):
                return
        except OSError:
            if attempt==2:
                raise RuntimeError("通知发送失败") from None
            time.sleep(2**attempt)


if __name__=="__main__":
    if os.getenv("WEBHOOK_URL"):
        send(os.environ["WEBHOOK_URL"],json.loads(Path("reports/latest.json").read_text(encoding="utf8")))
    else:
        print("未配置独立通知")
