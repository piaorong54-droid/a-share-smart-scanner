"""Tushare Pro JSON transport. All amounts converted at strategy boundary."""
import os
import json
import time
from urllib.request import Request, urlopen


class Provider:
    def __init__(self):
        self.token = os.environ["TUSHARE_TOKEN"]

    def rows(self, api, fields, **params):
        body = json.dumps(dict(api_name=api, token=self.token, params=params, fields=fields)).encode()
        for attempt in range(3):
            try:
                time.sleep(0.35)
                with urlopen(Request("https://api.tushare.pro", body, {"Content-Type": "application/json"}), timeout=15) as response:
                    payload = json.load(response)
                if payload["code"] != 0:
                    raise ValueError(f"{api} 拒绝请求 ({payload['code']})")
                data = payload["data"]
                if set(data["fields"]) != set(fields.split(",")):
                    raise ValueError(f"{api} 字段变化")
                return [dict(zip(data["fields"], row, strict=True)) for row in data["items"]]
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
