# 教员端

在本目录使用 Python 3.11 或更新版本运行：

```powershell
python -m pip install -r requirements.txt
python -X utf8 run.py
```

Web 默认地址为 http://127.0.0.1:8710/，可用 `--host` 和 `--port` 调整监听地址。
模型保存在 `data/models/`，运行状态保存在 `data/runtime/`，Web 和程序日志写入 `log/`。

## IEC104 仿真服务

启动教员 Web 后，在本目录独立运行 `python -X utf8 scada104.py`。默认从
`D:\codex\fes` 加载 `scdfe_s`，使用
`D:\codex\workspace\simulation\qinling\simulator\simulator\scdfe_s.sqlite3`。
可用 `--scada-root`、`--db`、`--simulator-url`、`--web-port` 和
`--first-iec104-port` 调整配置。Web 默认监听 8878，模型通道从 2404 起分配。

- 在教员端启动相应模型服务。首次发现在线模型时自动创建独立通道和四遥点表。
- 在 [通信监控](http://127.0.0.1:8878/communication) 查看通道地址与状态，在
  [通道测试](http://127.0.0.1:8878/test#points) 选择 RTU，查看实时点值和执行遥控、遥调。
  在 [点表配置](http://127.0.0.1:8878/points) 修改显示名称及规约映射。修改规约映射后重启该通道。
- 按模型、四遥类型和仿真点名保留点号。模型新增点时自动补齐，已有点的人工定义保留。
  模型删点时保留原记录和映射，遥测遥信标记无效，退役遥控遥调拒绝执行。
  实时值来源是模型的 SCADA 量测输出。IEC104 端口默认只监听本机。
