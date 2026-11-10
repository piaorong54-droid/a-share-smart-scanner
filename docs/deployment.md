# 部署与验收
从目标仓库 main 创建分支，将压缩包内容覆盖到仓库根目录（包括 .github），运行 python -m pip install pytest，然后 python -m pytest -q。审阅后提交并推送，由仓库维护者合并至默认分支。
 
在 Settings → Secrets and variables → Actions 设置 TUSHARE_TOKEN，需具备主板清单、交易日历、当日分钟、日线、复权因子、涨停价、每日指标和财务权限。WEBHOOK_URL 为可选接受 HTTPS JSON POST 的私有接收端，接收端应按 Idempotency-Key 去重。
 
在 Actions 启用工作流，交易日北京时间14:45至14:59手动运行 Daily scan。检查 artifact 的真实数据时间、覆盖率和 errors，并在接收端核对同一报告 ID。定时表达式 45 6 * * 1-5 使用 UTC；假期依据上交所日历跳过。延误到15:00后会失败。每次运行独立保存90天，手动重跑产生新 artifact；跨运行去重与长期最新报告托管尚待部署。
 
如连续十只均未核实，扫描提前结束并报告 PARTIAL_DATA。若盘中数据未发布，应更换有授权的实时源并对账。即便拿到 token，也需验证真实覆盖和单位；目前不宜作生产信号。
 
只读集成：解压已验证的 artifact 到项目 reports/，安装 python -m pip install "mcp[cli]>=1.9,<2"，运行 python server.py。本地服务由具备鉴权的 HTTPS 反向代理提供 /mcp，限制读取者。先验证 tools/list 和 get_latest_scan，再在支持连接器的 ChatGPT 工作区添加该地址并完成授权。Skill 位于 skills/a-share-tail-scanner。也可直接上传报告 JSON。需另外同步新 artifact，当前无托管服务、推送至聊天或远程触发能力。
