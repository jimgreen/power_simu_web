# 学员端

在本目录使用 Python 3.11 或更新版本运行：

```powershell
python -m pip install -r requirements.txt
python -X utf8 run.py
```

Web 默认地址为 http://127.0.0.1:8720/，可用 `--host` 和 `--port` 调整监听地址。
模型保存在 `data/models/`，运行状态保存在 `data/runtime/`，Web 和程序日志写入 `log/`。
