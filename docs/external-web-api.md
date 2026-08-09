# 模拟台外部 WEB 接口

## 1. 访问入口

外部程序首先读取模型交互链接：

```http
GET http://127.0.0.1:8710/api/trainee-link?model_id=秦岭站
```

返回中的 `teacher_api_base` 是接口根地址，`external_api` 给出本模型的全部外部接口路径：

```json
{
  "model_id": "秦岭站",
  "model_version": {
    "schema_version": 1,
    "revision": 3,
    "signature": "<sha256>",
    "algorithm": "sha256"
  },
  "external_api": {
    "devices": "/api/external/devices?model_id=秦岭站",
    "realtime_inputs": "/api/external/realtime-inputs?model_id=秦岭站",
    "telemetry_names": "/api/external/telemetry/names?model_id=秦岭站",
    "telemetry_values": "/api/external/telemetry/values?model_id=秦岭站",
    "selected_telemetry_values": "/api/external/telemetry/values/query?model_id=秦岭站",
    "measurement_history": "/api/external/telemetry/history/query?model_id=秦岭站",
    "control_names": "/api/external/controls/names?model_id=秦岭站",
    "control_execute": "/api/external/controls/execute?model_id=秦岭站"
  }
}
```

`model_id` 应当进行 URL 编码。外部程序不要自行拼接后续路径，优先采用交互链接返回的 `external_api`。

## 2. 一致性校验

交互链接和所有外部接口响应都带有相同结构的 `model_version`：

- `revision`：当前内存模型定义修订号。
- `signature`：模型、量测和控制定义内容的 SHA-256 签名。
- `schema_version`：版本对象结构版本。
- `algorithm`：签名算法。

名称接口和值接口另外返回 `definition_signature`，用于校验点表顺序。外部程序应遵守以下规则：

1. `model_version.signature` 不一致时，放弃本帧并重新获取交互链接和所有定义。
2. `definition_signature` 不一致时，放弃值帧并重新获取名称列表。
3. 名称列表和值列表长度不一致时，告警并放弃本帧。
4. 全量值列表严格按照对应名称列表的顺序排列，不需要逐点名称匹配。

运行值、仿真时钟和控制指令变化不会改变 `model_version`；模型、量测或控制定义变化会改变版本签名和修订号。

## 3. 全部设备信息

```http
GET /api/external/devices?model_id=秦岭站
```

返回内容包括：

- `devices`：所有节点、支路、电源、负荷、储能、变流器、开关和耦合设备。
- `devices[].topology`：设备端子及连接节点。
- `devices[].parameters`：设备主定义参数。
- `devices[].parameter_blocks`：风机、光伏和储能等关联参数块。
- `devices[].state`：投退、开合、死岛、控制模式和 SOC 等运行状态。
- `devices[].values`：该设备的全部遥测和遥信当前值。
- `devices[].control_values`：该设备的遥调和遥控当前值。
- `topology.nodes`、`topology.connections`：可直接用于重建拓扑关系的节点和连接表。

### 3.1 实时环境与负荷输入

读取字段、单位、负荷目录及下一目标曲线点：

```http
GET /api/external/realtime-inputs?model_id=秦岭站
```

提交外部实时边界：

```http
POST /api/external/realtime-inputs?model_id=秦岭站
Content-Type: application/json
```

单点输入：

```json
{
  "start_time": "00:10:00",
  "point_count": 1,
  "point_interval_seconds": 60,
  "weather": {
    "wind_speed_mps": 9.6,
    "solar_irradiance_w_m2": 650,
    "air_temp_c": -12,
    "air_pressure_hpa": 965,
    "humidity_pct": 70
  },
  "loads": {
    "ACLoad:交流负荷-1": 120,
    "DCLoad:直流负荷-1": 40
  }
}
```

兼容旧版单点请求：不提供起始时标、点数和间隔时，默认更新当前仿真时钟对应的下一未求解点。新接入程序应显式提供完整数据契约。

多点输入采用 `points` 数组。数组顺序与时刻顺序一致，每个点必须包含相同的天气字段和负荷字段：

```json
{
  "start_time": "00:10:00",
  "point_count": 2,
  "point_interval_minutes": 1,
  "points": [
    {
      "weather": {"wind_speed_mps": 9.6, "solar_irradiance_w_m2": 650},
      "loads": {"ACLoad:交流负荷-1": 120}
    },
    {
      "weather": {"wind_speed_mps": 9.8, "solar_irradiance_w_m2": 670},
      "loads": {"ACLoad:交流负荷-1": 125}
    }
  ]
}
```

整段或整条曲线采用 `series`。每条数组长度必须等于 `point_count`：

```json
{
  "start_time": "00:00:00",
  "point_count": 3,
  "point_interval_seconds": 60,
  "series": {
    "weather": {
      "wind_speed_mps": [8.0, 8.2, 8.5],
      "solar_irradiance_w_m2": [0, 20, 50]
    },
    "loads": {
      "ACLoad:交流负荷-1": [100, 105, 110],
      "DCLoad:直流负荷-1": [30, 32, 35]
    }
  }
}
```

`series` 也支持扁平键，例如 `"wind_speed_mps": [...]` 和 `"load:ACLoad:交流负荷-1": [...]`。负荷单点还支持 `load_values` 数组形式。

处理规则：

- 接口只在模拟台提供，学员台返回 `404`，不会把该请求代理到模拟台。
- 批量输入必须定义 `start_time`、`start_absolute_minute` 或 `start_absolute_second`。时标是曲线定位的权威依据，后续点时刻按“起始时刻 + 点序号 × 数据点间隔”计算。
- `start_time` 支持 `HH:MM[:SS]` 和 `天数+HH:MM[:SS]`。起始时刻必须落在当前曲线采样网格上；可选 `start_index` 仅用于一致性校验，不能替代时标。
- 批量输入必须定义正整数 `point_count`，并定义且只能定义一种间隔：`point_interval_seconds` 或 `point_interval_minutes`。间隔必须是 GET 接口返回的当前曲线采样间隔的正整数倍；每个数据点按计算出的实际时刻定位曲线点。
- `points` 数组长度必须等于 `point_count`，并且每个点的天气字段、负荷字段集合必须一致。`series` 中每条数组长度也必须等于 `point_count`。
- 请求按时刻更新 `runtime/curves.json` 中对应曲线点，不修改原始 `curves.json`，也不主动推进仿真时钟。
- 对应仿真时刻到达后，常规潮流计算会读取新值；如果潮流正在计算，请求会等待该轮完成后再一次性写入，不会使已完成结果因曲线修订而被丢弃。
- 负荷标准键为 `ACLoad:设备名` 或 `DCLoad:设备名`。裸设备名只有在当前模型内唯一时才接受；同名交流、直流负荷必须使用标准键。
- 风速、太阳辐射和负荷不能为负数，湿度范围为 `0..100`，气压必须大于 `0`，所有值必须是有限数值。
- 一帧先完成时标、间隔、点数、数组长度、字段完整性、设备名称和数值范围校验，再执行一次写入。任一项不合规时，整帧返回 `400`，不做部分更新。

成功响应给出 `update_mode`、`input_point_count`、`point_interval_seconds`、`start_simu_time`、`end_simu_time`、`updated_indices`、`curve_revision` 和 `curve_boundary`。`applies_on_next_power_flow=true` 表示更新范围包含下一未求解点；其他未来时刻的数据会在仿真时钟到达对应时刻时生效。

## 4. 遥测和遥信名称

```http
GET /api/external/telemetry/names?model_id=秦岭站
```

主要返回字段：

```json
{
  "model_id": "秦岭站",
  "simu_time": "12:30:00",
  "model_version": {"revision": 3, "signature": "<sha256>"},
  "definition_signature": "<sha256>",
  "telemetry_names": ["遥测名1", "遥测名2"],
  "signal_names": ["遥信名1", "遥信名2"]
}
```

兼容别名为 `yc_names` 和 `yx_names`。

## 5. 全部遥测和遥信值

```http
GET /api/external/telemetry/values?model_id=秦岭站
```

主要返回字段：

```json
{
  "model_id": "秦岭站",
  "simu_time": "12:30:00",
  "model_version": {"revision": 3, "signature": "<sha256>"},
  "definition_signature": "<sha256>",
  "telemetry_count": 583,
  "signal_count": 218,
  "telemetry_values": [12.0, 380.1],
  "signal_values": [1, 0],
  "telemetry_valid": [1, 1],
  "signal_valid": [1, 1]
}
```

`telemetry_values` 与 `telemetry_names` 一一对应，`signal_values` 与 `signal_names` 一一对应。兼容别名为 `yc_values` 和 `yx_values`。

系统自动生成的遥测、遥信、遥调和遥控名称统一采用 `设备类型.设备名称.点类型`，设备类型参与名称可避免不同类型设备同名时发生冲突。

## 6. 指定遥测和遥信值

```http
POST /api/external/telemetry/values/query?model_id=秦岭站
Content-Type: application/json
```

请求：

```json
{
  "telemetry_names": ["Environment.weather.WIND_SPEED", "ACLoad.load_ac_1.P_LOAD"],
  "signal_names": ["ACGenerator.diesel_300kw.run_stat"]
}
```

返回值保持请求顺序，并提供 `telemetry_found`、`signal_found` 和 `missing`。不存在的点返回 `null`、`valid=0`、`found=false`。

## 7. 历史遥测和遥信曲线

```http
POST /api/external/telemetry/history/query?model_id=秦岭站
Content-Type: application/json
```

一次请求可以同时查询多条遥测和多条遥信：

```json
{
  "start_time": "00:00:00",
  "end_time": "02:00:00",
  "interval_seconds": 300,
  "telemetry_names": [
    "Environment.weather.WIND_SPEED",
    "ACLoad.load_ac_1.P_LOAD"
  ],
  "signal_names": [
    "ACGenerator.diesel_300kw.run_stat",
    "ACBreak.交流开关-1.status"
  ]
}
```

时间参数支持以下形式：

- `start_time`、`end_time`：`HH:MM[:SS]`，也支持 `天数+HH:MM[:SS]`，例如 `2+03:00:00`。
- `start_absolute_minute`、`end_absolute_minute`：累计仿真分钟，适合周、月、年仿真，且优先于同名 `*_time` 参数。
- `start_absolute_second`、`end_absolute_second`：累计仿真秒。
- `interval_seconds`：返回数据的采样间隔，必须大于 0。

主要返回字段：

```json
{
  "model_id": "秦岭站",
  "model_version": {"revision": 3, "signature": "<sha256>"},
  "definition_signature": "<sha256>",
  "run_id": 7,
  "interval_seconds": 300,
  "value_layout": "time-major",
  "absolute_minutes": [0, 5, 10],
  "simu_times": ["00:00:00", "00:05:00", "00:10:00"],
  "source_absolute_minutes": [0, 5, 10],
  "source_wall_times": ["2026-08-08T10:00:00", "2026-08-08T10:00:05", "2026-08-08T10:00:10"],
  "telemetry_names": ["遥测1", "遥测2"],
  "signal_names": ["遥信1", "遥信2"],
  "telemetry_values": [[10.1, 20.2], [10.3, 20.4], [10.5, 20.6]],
  "signal_values": [[1, 0], [1, 1], [0, 1]],
  "telemetry_valid": [[1, 1], [1, 1], [1, 1]],
  "signal_valid": [[1, 1], [1, 1], [1, 1]]
}
```

数组采用时间优先布局：

- `telemetry_values[i][j]` 表示第 `i` 个采样时刻、第 `j` 个 `telemetry_names` 测点的值。
- `signal_values[i][j]` 表示第 `i` 个采样时刻、第 `j` 个 `signal_names` 测点的值。
- `source_absolute_minutes` 表示每个返回值实际采用的后台历史帧时刻。
- `source_wall_times` 表示对应历史帧在模拟台本机的采集时刻。
- 当请求间隔小于仿真采样间隔时，接口采用采样时刻之前最近一帧，不对遥测进行线性造值，遥信也不会提前采用未来状态。
- 请求时段只返回后台现有历史范围内的数据；`available_*` 和 `effective_*` 字段分别给出可用范围和实际返回范围。
- 未找到或点类型不匹配的名称保持原请求位置，值为 `null`、有效位为 `0`，并通过 `telemetry_found`、`signal_found`、`missing` 说明。
- 单次请求的遥测和遥信名称总数最多 256 个，返回采样点最多 10000 个。
- 历史缓存只覆盖当前仿真轮次；仿真重新开始、归零或模型定义变化后，上一轮历史会被清空。

兼容别名为 `yc_names`、`yx_names`、`yc_values` 和 `yx_values`。

## 8. 遥调和遥控名称

```http
GET /api/external/controls/names?model_id=秦岭站
```

主要返回字段：

```json
{
  "model_id": "秦岭站",
  "simu_time": "12:30:00",
  "model_version": {"revision": 3, "signature": "<sha256>"},
  "definition_signature": "<sha256>",
  "remote_adjustment_names": ["ACGenerator.柴油发电机-1.p_set"],
  "remote_control_names": ["ACBreak.盒型开关-1.status"]
}
```

兼容别名为 `yt_names` 和 `yk_names`。

## 9. 提交遥调和遥控

```http
POST /api/external/controls/execute?model_id=秦岭站
Content-Type: application/json
```

请求中的名称和值必须等长：

```json
{
  "remote_adjustment_names": ["ACGenerator.柴油发电机-1.p_set"],
  "remote_adjustment_values": [60.0],
  "remote_control_names": ["ACBreak.盒型开关-1.status"],
  "remote_control_values": [0],
  "valid_for_minutes": 10,
  "source": "external-ems"
}
```

响应中的 `remote_adjustment_results` 和 `remote_control_results` 与请求顺序一致，每项包括：

- `requested_value`：请求值。
- `value`：模拟台执行后的当前值。
- `found`：控制名称是否存在且类型正确。
- `accepted`：指令是否已成为有效指令。
- `active`：当前是否仍处于有效期。
- `reason`：未接受原因。
- `expires_at_absolute_minute`：自动指令失效时刻。
- `command_origin`：人工或自动来源。

未指定人工属性时，外部接口按自动指令处理，默认有效期为 120 个仿真分钟。可通过 `valid_for_minutes` 设置有效期。需要一直有效、人工退出的指令可显式传入：

```json
{
  "command_origin": "manual",
  "hold_until_cancelled": true
}
```

## 10. PowerShell 调用示例

```powershell
$link = Invoke-RestMethod -Uri "http://127.0.0.1:8710/api/trainee-link?model_id=秦岭站"
$base = $link.teacher_api_base

$names = Invoke-RestMethod -Uri ($base + $link.external_api.telemetry_names)
$frame = Invoke-RestMethod -Uri ($base + $link.external_api.telemetry_values)

$inputBody = @{
  start_time = "00:00:00"
  point_count = 1
  point_interval_seconds = 60
  weather = @{
    wind_speed_mps = 9.6
    solar_irradiance_w_m2 = 650
  }
  loads = @{
    "ACLoad:交流负荷-1" = 120
    "DCLoad:直流负荷-1" = 40
  }
} | ConvertTo-Json -Depth 5

$inputResult = Invoke-RestMethod -Method POST `
  -Uri ($base + $link.external_api.realtime_inputs) `
  -ContentType "application/json" `
  -Body $inputBody

if ($names.model_version.signature -ne $frame.model_version.signature -or
    $names.definition_signature -ne $frame.definition_signature -or
    $names.telemetry_names.Count -ne $frame.telemetry_values.Count -or
    $names.signal_names.Count -ne $frame.signal_values.Count) {
  throw "模拟台模型或点表版本不一致，本帧已丢弃"
}

$historyBody = @{
  start_time = "00:00:00"
  end_time = "01:00:00"
  interval_seconds = 60
  telemetry_names = @("Environment.weather.WIND_SPEED", "p_load_load_ac_1")
  signal_names = @("ACGenerator.diesel_300kw.run_stat")
} | ConvertTo-Json -Depth 5

$history = Invoke-RestMethod -Method POST `
  -Uri ($base + $link.external_api.measurement_history) `
  -ContentType "application/json" `
  -Body $historyBody

$body = @{
  remote_adjustment_names = @("ACGenerator.柴油发电机-1.p_set")
  remote_adjustment_values = @(60.0)
  valid_for_minutes = 10
  source = "external-ems"
} | ConvertTo-Json -Depth 5

$result = Invoke-RestMethod -Method POST `
  -Uri ($base + $link.external_api.control_execute) `
  -ContentType "application/json" `
  -Body $body
```

## 11. 网络访问说明

当前使用 `--host 127.0.0.1` 启动时，只允许模拟台本机程序访问。其他计算机需要将服务绑定到受控网卡地址或 `0.0.0.0`，并在防火墙中只开放所需来源。接口支持 CORS 和 gzip，但目前没有内置身份认证；不要直接暴露到不可信网络。
