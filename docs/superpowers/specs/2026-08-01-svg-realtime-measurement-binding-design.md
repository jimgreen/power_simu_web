# SVG 实时量测绑定设计

## 目标

模拟台和学员台在接线图页面解析模型 SVG，并将当前模型的实时量测值写入 SVG 自带的量测占位符。模型切换、SVG 更新和量测增量刷新后，图形中的值必须与当前模型保持一致。

## 现状与根因

前端已经支持 `data-meas-name`、`data-scada-name`、`data-real-name` 和 `data-control-name` 精确绑定，也已经在接线图页面请求量测增量并周期性调用图形渲染函数。

现有模型 SVG 不使用这些属性，而是使用以下语义结构：

```xml
<g class="mg" dev="ACGenerator-1">
  <tspan class="mv" mt="activePower">--</tspan>
  <tspan class="mv" mt="reactivePower">--</tspan>
  <tspan class="mv" mt="voltage">--</tspan>
</g>
```

设备实例本身通过同一个 SVG 中的 `id`、`dev-id` 和 `name` 属性定义：

```xml
<use id="ACGenerator-1" dev-id="ACGenerator-1" name="交流风电-1" />
```

因此现有绑定函数找不到实际的 `.mv[mt]` 占位符，所有值持续显示为 `--`。

## 方案

### 绑定优先级

1. 保留并优先处理现有的精确绑定属性。
2. 对没有精确绑定属性的 `.mv[mt]` 元素执行自动语义绑定。
3. 自动绑定优先使用遥测值 `measurements.scada`，没有对应遥测行时回退到 `measurements.real`。
4. 没有匹配量测或量测值为空时显示 `--`，不使用定义文件中的默认值冒充实时值。

### SVG 设备解析

SVG 首次加载或图形版本变化时执行一次解析：

1. 建立 `dev-id/id -> { devType, devName }` 索引。
2. 查找所有处于 `[dev]` 容器内的 `.mv[mt]` 元素。
3. 将每个占位元素编译为 `{ element, devType, devName, metricType }` 绑定描述。
4. 将绑定描述缓存到当前接线图容器；普通量测刷新只更新文本，不重复解析整个 SVG。

模型或 SVG 变化时，现有 `diagramKey` 机制会重建 SVG，绑定缓存随之失效并重新生成。

### 量测类型映射

按设备类型优先匹配最符合图形语义的量测类型，再使用通用候选作为兼容回退：

| SVG 指标 | 设备类型 | 优先量测类型 |
| --- | --- | --- |
| `activePower` | `ACGenerator`、`DCGenerator` | `P_GEN` |
| `activePower` | `ACLoad` | `P_LOAD` |
| `activePower` | `DCACConverter` | `P_AC`，回退 `P_DC` |
| `activePower` | `DCDCConverter` | `P_TO`，回退 `P_FROM` |
| `activePower` | 支路、开关、零阻抗支路 | `P_FROM`，回退 `P_TO` |
| `reactivePower` | 发电机、负荷、交直流变流器、交流支路 | 对应的 `Q_GEN`、`Q_LOAD`、`Q_AC`、`Q_FROM/Q_TO` |
| `voltage` | 发电机、负荷 | `V_GEN`、`V_LOAD` |
| `voltage` | `DCACConverter` | `V_AC`，回退 `V_DC` |
| `voltage` | `DCDCConverter` | `V_TO`，回退 `V_FROM` |
| `current` | 各设备 | 对应的 `I_GEN`、`I_LOAD`、`I_AC/I_DC`、`I_TO/I_FROM` 或 `I` |
| `status` | 开关及通用设备 | `STATUS`，回退 `RUN_STAT` |
| `level` | 储能设备 | `SOC`，回退 `LEVEL` |
| `frequency` | 通用 | `FREQUENCY`、`FREQ`、`F` |
| `flow`、`pressure`、`temperature` | 通用 | 同名大写量测类型 |

所有类型匹配忽略大小写，但设备类型和设备名称必须对应当前模型，禁止跨设备取值。

### 数值显示

- 普通量测沿用当前两位小数格式，不做 `abs`、`min`、`max` 或正负号修正。
- `SOC` 在模型中使用标幺值，SVG 的 `level` 占位符带 `%` 单位，因此仅做 `value * 100` 的单位换算，不限制在 `0%` 至 `100%`。
- 周围单位文本由原 SVG 保留，绑定函数只替换 `.mv` 占位符内容。
- 未匹配值保持 `--`，并移除已绑定样式，避免旧模型数值残留。

## 数据流

```text
服务端量测快照/增量
  -> 前端更新 state.snapshot.measurements
  -> 当前页面为 diagram 时调用 renderModelDiagramPage
  -> 复用或创建 SVG 绑定描述
  -> 按设备和量测类型查找 scada/real 行
  -> 只更新对应 tspan 文本和绑定状态
```

学员台继续只通过学员台服务端获取量测；本功能不会让学员台页面直接访问模拟台服务端。

## 性能与错误处理

- 不新增 HTTP 接口或额外轮询。
- SVG 结构只在图形变化时解析一次。
- 每轮刷新建立量测索引并按绑定数量做线性更新。
- 格式不完整、设备不存在或指标无法映射时跳过该绑定，不影响其他量测点。
- 显式 `data-*` 绑定保持向后兼容，并覆盖自动推断结果。

## 测试

1. 纯函数测试设备类型与 SVG 指标到量测类型候选的映射。
2. 测试 `dev-id/id + name` 能解析为当前模型设备。
3. 测试自动绑定选择遥测值，并在遥测缺失时回退实时值。
4. 测试 `SOC` 转为百分比但不裁剪越界值。
5. 保留现有精确绑定回归测试。
6. 在模拟台和学员台接线图页面使用实际秦岭站 SVG 验证占位符由 `--` 更新为实时数值，并检查控制台无错误。

## 非目标

- 不修改或重写用户导入的 SVG 文件。
- 不自动生成 SVG 中不存在的量测框。
- 不增加量测历史曲线、告警着色或设备动画。
- 不改变服务端量测计算、量纲或有效性判断。
