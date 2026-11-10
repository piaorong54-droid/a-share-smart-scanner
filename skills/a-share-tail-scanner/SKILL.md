---
name: a-share-tail-scanner
description: 查询 A 股尾盘扫描报告、核查时效及逐股判定。
---
读取用户提供的报告 JSON 或调用 get_latest_scan。核对 date、mode、started、market_time、verified/total、status。日期不匹配时给出实际日期。只引用 matches 中的股票。遇到缺失或部分数据时说明无法确认。按代码查询 details 和 errors。用户请求运行时引导有权限者手动运行 Daily scan。
