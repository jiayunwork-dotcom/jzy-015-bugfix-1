# 海岸线性重力波色散反演服务

给定海况（水深 `water_depth` h、波高 `wave_height` H、周期 `period` T，均为 SI 单位），
按线性波理论求解色散波数，并导出波长、相速度、群速度、相对水深分区与波面高程。
通过 HTTP 对外，PostgreSQL 16 落库，Docker Compose 一条命令拉起。

## 一条命令启动

```bash
docker compose up --build
# API: http://localhost:8000  （交互式文档 /docs）
# PostgreSQL 16: localhost:5432
```

首次启动会等待数据库健康并自动建表（`wave_calculations`）。

## 物理定义（全服务统一，唯一常数来源 `app/config.py`）

| 量 | 定义 |
|---|---|
| 角频率 | ω = 2π / T |
| 重力加速度 | g = **9.80665 m/s²**（钉死，任何模块不得再定义本地 g） |
| 色散方程 | ω² = g·k·tanh(kh)，迭代求根，容差 1e-12，最大 100 次，无法闭合即拒绝（双曲正切 **tanh**，不是 tan） |
| 分区 | kh > π 深水；kh < π/10 浅水；其间中等水深（**一律走完整 tanh**，不偷换深水闭式） |
| 波长 | L = 2π/k |
| 相速度 | c = ω/k（与色散共用同一个 k） |
| 群速度 | cg = (c/2)·(1 + 2kh/sinh(2kh))；深水 n→1 ⇒ cg→c/2，浅水 n→2 ⇒ cg→c |
| 波面高程 | η(x,t) = (H/2)·cos(k·x − ω·t)，全服务同一相位约定 |
| 线性适用上限 | H/h ≤ **0.5**（超过直接拒绝，上限可在 `/config` 读到） |

自检极限：深水 c₀ = gT/2π、L₀ = gT²/2π；浅水 cs = √(gh)。

### ⚠️ 关于“中等水深相速度介于两个闭式之间”

由色散方程可严格推出（同一 h、同一 T）：

```
c = c₀·√(tanh(kh)/kh) < c₀ = gT/2π
c = √(gh)·√(tanh(kh)/kh) < √(gh)
```

即精确相速度**严格小于深水闭式与浅水闭式中的任意一个**——两个闭式都是上界，
因此“严格落在两者之间”在数学上不成立（除非把浅水闭式误用成无界的 √gh 序列）。
本服务按正确物理实现：示范算例返回 `strict_checks`，明确验证 c 同时小于两个极限，
且 kh 明确落在 (π/10, π) 内并真正满足完整色散残差 ≤ 容差。
“介于深、浅水速度之间”的物理图像应理解为：**同一列波**从外海向浅水传播时，
速度由深水值连续下降到浅水值，沿途中点的速度介于外海深水值与更浅处浅水值之间。

## 接口

| 方法 路径 | 说明 |
|---|---|
| `POST /solve` | 解一条海况，返回色散解 + 全部导出量；支持 `positions`/`times` 网格 |
| `POST /solve/batch` | 批量；逐条核算，坏条点明 `index`/`field`，其余照常返回与落库 |
| `GET  /demo` | 中等水深涌浪示范（h=10 m, H=2 m, T=8 s，kh≈0.887，只读） |
| `GET  /history` | 历史检索：`regime/status/min_period/max_period/min_water_depth/max_water_depth/limit/offset` |
| `GET  /config` | 回显 g、π 与 π/10 判据、线性上限、求根容差 |
| `GET  /health` | 监控状态（含数据库连通性） |

波面网格维度约定：`eta[i][j]` = `times[i] × positions[j]`（行随时间、列随位置）。

```bash
curl -s localhost:8000/solve -H 'content-type: application/json' -d '{
  "water_depth": 10, "wave_height": 2, "period": 8,
  "positions": [0, 25, 50], "times": [0, 4]
}'

curl -s localhost:8000/solve/batch -H 'content-type: application/json' -d '{
  "items": [
    {"water_depth": 10, "wave_height": 2, "period": 8},
    {"water_depth": 10, "wave_height": 9, "period": 8}
  ]
}'
```

非法输入返回 HTTP 422，形如：

```json
{"status":"error","error":{"code":"LINEAR_LIMIT_EXCEEDED","field":"wave_height",
 "message":"波高/水深 = 0.9 超过线性适用上限 0.5"}}
```

批量中错误条的 `error.code` ∈ `INVALID_PARAMETER` / `LINEAR_LIMIT_EXCEEDED` /
`DISPERSION_NOT_CONVERGED`。成功与失败的每次核算都会落库（失败条存输入与错误信息）。

## 模块划分

```
app/
  config.py       # 唯一的 g 与全部钉死参数
  dispersion.py   # 色散求根（Eckart 初值 + 带保护 Newton/二分兜底）
  kinematics.py   # 波长/相速度/群速度（共用 dispersion 的 k）/分区
  elevation.py    # 波面高程与网格（统一 cos(kx−ωt) 约定）
  validation.py   # 类型/有限性/正性/线性上限校验
  persistence.py  # PostgreSQL 仓储 + 条件检索（另有内存实现供测试）
  wave.py         # 计算编排（纯函数，无共享可变状态）
  routes/         # meta / solve / history
  main.py         # 应用装配、统一错误处理、启动建表
tests/            # 物理判据、接口、批量部分失败、落库、并发互不串扰
```

求根器：Eckart(1952) 显式近似给出覆盖深/浅水的高质量初值，Newton 迭代
`k ← k − F/F′`（`F′=g(tanh kh + kh·sech² kh)`），Newton 点越界或不缩窄括号时
退化为二分；括号 `[lo,hi]` 始终包住唯一根，故对任何合法输入保证闭合。

## 测试

```bash
pip install -r requirements.txt pytest httpx
pytest                 # 零外部依赖（接口测试使用线程安全内存仓储）
```

覆盖：深水 c=gT/2π、浅水 c=√(gh)、中等水深完整色散与严格不等式、
周期翻倍波长≈4×/相速度×2、加深饱和、浅水水深 4× 则速度 2×、
波高翻倍只放大高程不改 k/c/cg、群速度 sinh 修正、波陡越限拒绝、
各类非法参数（含 NaN/Infinity、批量按条报错）、批量部分失败、历史落库与过滤、
5 线程 × 6 次并发互不串扰。
