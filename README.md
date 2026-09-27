# 离线软件依赖求解 API

基于 Python + FastAPI 的**纯离线**软件依赖求解服务：求解只使用请求体中自带的 `catalog`，
**不会联网查询任何包仓库或其他外部服务**。

- 服务端口：**8000**
- 求解接口：`POST /solve`
- 冲突定位接口：`POST /conflicts`
- 健康检查：`GET /health`
- 交互式文档（服务启动后）：<http://localhost:8000/docs>

## 一、快速开始（Docker Compose）

需要已安装 Docker 与 Docker Compose 插件。一条命令即可构建镜像、安装依赖并启动服务：

```bash
docker compose up --build
```

看到类似下面的输出即表示就绪：

```text
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

之后服务监听在 <http://localhost:8000>。后台运行可用：

```bash
docker compose up --build -d
docker compose logs -f      # 查看日志
docker compose down         # 停止并移除
```

## 二、请求格式

`POST /solve`，`Content-Type: application/json`，请求体包含两个字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `catalog` | 对象 | 包目录：包名 → 版本数组。最多 **8** 个包，每个包 **1～5** 个版本。 |
| `roots` | 对象（非空） | 根约束：包名 → 正整数闭区间 `[min, max]`。 |

每个版本项包含：

- `version`：正整数版本号；同一包内不得重复。
- `dependencies`：对象，依赖包名 → 正整数闭区间 `[min, max]`，含义与 `roots` 相同，
  依赖可传递，**允许可满足的循环依赖**。

### 约束规则

- 只选择从 `roots` 出发、沿所选版本的依赖边可达的包；每个被选包恰好选择一个版本。
- 所有根约束与传递依赖的区间约束（闭区间，含端点）都必须满足。
- 同一约束下存在多个解时：把**全部包名按字典序升序排列**构成版本向量，
  未选中的包记为 `0`，取该向量**字典序最大**的解。
- 以下输入非法，返回 **HTTP 422**：
  - 区间不是两个正整数、或下界大于上界（如 `[3, 1]`、`[0, 1]`）；
  - 同一包出现重复 `version`；
  - `roots` 或任何 `dependencies` 引用了 `catalog` 中不存在的包名；
  - 包数超过 8、每包版本数不在 1～5、`roots` 为空、出现多余字段等。

### 响应

可满足：

```json
{ "satisfiable": true, "selected": { "app": 2, "lib": 3 } }
```

不可满足（冲突、无解）：

```json
{ "satisfiable": false, "selected": {} }
```

## 三、`POST /conflicts`：定位最小冲突根集合

请求体与 `POST /solve` **完全相同**（同样的 `catalog`、`roots`、同样的校验规则，
非法输入同样返回 **HTTP 422**），离线求解语义也一致。响应字段：

| 字段 | 说明 |
| --- | --- |
| `satisfiable` | 原请求（全部根约束）是否可满足。 |
| `conflict_roots` | 可满足时为 `[]`；无解时为基数最小的无解药根子集的包名（按字典序排列）。并列时取包名向量字典序最小者。 |
| `witnesses` | 可满足时为 `{}`；无解时对冲突组内每个根，以其包名为键，给出**移除该根、仅用组内其余根**求解得到的 `selected`（沿用 `/solve` 的版本向量择优规则）；组内只剩该根（移除后无根）时为 `{}`。 |

即：每个 witness 都是「删掉这个根冲突就消失」的证据，且求解时只考虑冲突组内的其余根，
不使用组外的根。

### 响应

可满足：

```json
{ "satisfiable": true, "conflict_roots": [], "witnesses": {} }
```

无解（两个根互相冲突；删掉任一个后，只靠另一个根都能解出相应选择）：

```json
{
  "satisfiable": false,
  "conflict_roots": ["a", "c"],
  "witnesses": {
    "a": {"b": 2, "c": 1},
    "c": {"a": 1, "b": 1}
  }
}
```

无解且最小冲突集合只有一个根（该根自身无解；移除后无剩余根，witness 为 `{}`）：

```json
{
  "satisfiable": false,
  "conflict_roots": ["app"],
  "witnesses": {"app": {}}
}
```

## 四、请求示例

### 示例 1：基本求解（含传递依赖、多解择优）

```bash
curl -s http://localhost:8000/solve \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {
      "app": [
        {"version": 1, "dependencies": {"lib": [1, 2]}},
        {"version": 2, "dependencies": {"lib": [2, 3]}}
      ],
      "lib": [
        {"version": 1, "dependencies": {}},
        {"version": 2, "dependencies": {}},
        {"version": 3, "dependencies": {}}
      ]
    },
    "roots": {"app": [1, 2]}
  }'
```

候选解包括 `(app,lib) = (1,1)/(1,2)/(2,2)/(2,3)`，版本向量字典序最大者为：

```json
{"satisfiable": true, "selected": {"app": 2, "lib": 3}}
```

### 示例 2：可满足的循环依赖

```bash
curl -s http://localhost:8000/solve \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {
      "a": [{"version": 1, "dependencies": {"b": [1, 1]}}],
      "b": [{"version": 1, "dependencies": {"a": [1, 1]}}]
    },
    "roots": {"a": [1, 1]}
  }'
```

响应：

```json
{"satisfiable": true, "selected": {"a": 1, "b": 1}}
```

### 示例 3：冲突，需要回溯后仍无解

```bash
curl -s http://localhost:8000/solve \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {
      "app": [{"version": 1, "dependencies": {"lib": [5, 9]}}],
      "lib": [
        {"version": 1, "dependencies": {}},
        {"version": 2, "dependencies": {}}
      ]
    },
    "roots": {"app": [1, 1]}
  }'
```

响应：

```json
{"satisfiable": false, "selected": {}}
```

### 示例 4：非法区间（422）

```bash
curl -i http://localhost:8000/solve \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {"app": [{"version": 1, "dependencies": {}}]},
    "roots": {"app": [3, 1]}
  }'
```

返回 `HTTP/1.1 422 Unprocessable Entity`，响应体说明具体校验错误。

### 示例 5：`/conflicts` 定位两个根的冲突（含 witnesses）

`a` 选中的版本要求 `b` 恰好为 1，`c` 选中的版本要求 `b` 恰好为 2，
两个根各自可满足、放在一起无解，最小冲突组就是 `["a", "c"]`：

```bash
curl -s http://localhost:8000/conflicts \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {
      "a": [{"version": 1, "dependencies": {"b": [1, 1]}}],
      "b": [
        {"version": 1, "dependencies": {}},
        {"version": 2, "dependencies": {}}
      ],
      "c": [{"version": 1, "dependencies": {"b": [2, 2]}}]
    },
    "roots": {"a": [1, 1], "c": [1, 1]}
  }'
```

响应（每个 witness 只保留冲突组内的另一个根，并按版本向量规则择优）：

```json
{
  "satisfiable": false,
  "conflict_roots": ["a", "c"],
  "witnesses": {
    "a": {"b": 2, "c": 1},
    "c": {"a": 1, "b": 1}
  }
}
```

### 示例 6：`/conflicts` 原请求可满足

```bash
curl -s http://localhost:8000/conflicts \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {"app": [{"version": 1}, {"version": 2}]},
    "roots": {"app": [1, 2]}
  }'
```

响应：

```json
{"satisfiable": true, "conflict_roots": [], "witnesses": {}}
```

## 五、实现说明

- `app/schemas.py`：基于 Pydantic 的请求模型与全部输入校验（失败由 FastAPI 转为 422）。
  `/solve` 与 `/conflicts` 共用同一请求模型 `SolveRequest`。
- `app/solver.py`：回溯求解器。维护已选版本、累积区间约束和可达包集合，
  发现冲突即回溯换版；版本降序尝试并配合乐观上界做分支限界，
  找到字典序最大解后快速剪枝。`minimum_conflict_roots` 按基数从小到大、
  同基数按包名字典序枚举根的非空子集（对有序输入使用
  `itertools.combinations`），第一个无解子集即最小冲突组；witnesses
  复用同一 `solve`，因此天然继承版本向量择优语义。
- `app/main.py`：FastAPI 应用与 `/solve`、`/conflicts`、`/health` 路由。

## 六、本地开发与测试（不使用 Docker）

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
uvicorn app.main:app --reload --port 8000
```

测试覆盖：传递依赖、循环依赖、冲突回溯、不可满足、字典序择优、各类 422 非法输入；
另有用随机 catalog 与暴力枚举逐一比对的正确性校验（脚本不在仓库内，可用上述开发环境自行扩展）。
