# CPA Usage Keeper

[English README](./README.en.md)

`CPA Usage Keeper` 是一个独立的 CPA 用量持久化与可视化服务。

它依赖 [CLIProxyAPI（CPA）](https://github.com/router-for-me/CLIProxyAPI) 作为后端 CPA 数据来源，目标是在 CPA 之上补充持久化存储与统计分析能力。服务会定时拉取 CPA 数据，将规范化后的事件写入 SQLite，暴露聚合 API，并提供内置 Web Dashboard 用于查看 usage、pricing、request health 和 model/API 维度的统计信息。

![cpa-usage-keeper-screenshot](https://images.bitskyline.com/i/2026/04/h9se9f.png)

## 功能特性

- CPA usage 数据持久化到 SQLite
- usage 聚合 API 与 pricing API
- 内置 React Dashboard
- 可选密码登录保护
- SQLite 数据库本地备份与保留策略

## 技术栈

- **后端**: Python 3.12+ / FastAPI / SQLAlchemy / SQLite
- **包管理**: uv
- **前端**: React + TypeScript (Vite)

## 安装

### 方式一：通过 uv（推荐）

```bash
uv tool install cpa-usage-keeper
```

安装后 `cpa-usage-keeper` 命令即可全局使用。升级：

```bash
uv tool upgrade cpa-usage-keeper
```

### 方式二：通过 pip

```bash
pip install cpa-usage-keeper
```

## 快速开始

1. 下载配置模板并按实际情况修改：

```bash
curl -fsSL https://raw.githubusercontent.com/8DE4732A/cpa-usage-keeper/main/config.example.toml -o config.toml
```

至少需要填写 `[cpa]` 节的 `base_url` 和 `management_key`。

2. 在 `config.toml` 所在目录直接运行（自动加载同目录的 `config.toml`）：

```bash
cpa-usage-keeper
```

或显式指定配置文件路径：

```bash
cpa-usage-keeper -c /path/to/config.toml
```

3. 打开浏览器访问 `http://localhost:8080`（端口可在配置中修改）。

## 项目结构

```text
src/cpa_usage_keeper/    Python 后端源码
  app.py                 FastAPI 应用工厂与生命周期管理
  config.py              环境配置加载
  database.py            SQLAlchemy 数据库初始化
  models.py              ORM 模型
  cpa/                   CPA 客户端与类型定义
  api/                   HTTP 路由处理器
  service/               同步与业务服务
  repository/            数据库访问层
  poller/                后台同步轮询
  auth/                  内存 session 鉴权
  redact/                数据脱敏
  backup.py              SQLite 数据库备份管理
  logging_config.py      日志配置
web/                     React + TypeScript 前端
static/                  前端构建产物 (gitignore)
```

## 配置

复制配置模板：

```bash
cp config.example.toml config.toml
```

配置文件按功能分节，以下是各配置项说明：

**`[cpa]`**

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `base_url` | 是 | - | CPA 服务地址 |
| `management_key` | 是 | - | CPA management key |
| `request_timeout` | 否 | `30s` | CPA 请求超时 |

**`[app]`**

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `port` | 否 | `8080` | HTTP 监听端口 |
| `base_path` | 否 | 根路径 | 子路径部署前缀，例如 `/cpa`；留空表示 `/` |
| `timezone` | 否 | `Asia/Shanghai` | 项目业务时区，影响 Today、按天聚合、每日清理和日志时间 |

**`[auth]`**

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | 否 | `false` | 是否启用登录保护 |
| `password` | 鉴权启用时必填 | - | 登录密码 |
| `session_ttl` | 否 | `168h` | Session 生命周期 |

**`[sync]`**

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `mode` | 否 | `auto` | 同步模式：`auto`、`redis`、`legacy_export` |
| `poll_interval` | 否 | `5m` | `legacy_export` 拉取间隔 |

**`[redis]`**

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `queue_addr` | 否 | `base_url` 主机名 + `8317` | CPA Redis/RESP TCP 地址 |
| `queue_batch_size` | 否 | `1000` | 每次最多拉取的队列记录数 |
| `queue_idle_interval` | 否 | `1s` | 队列为空时的检查间隔 |

**`[storage]`**

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `work_dir` | 否 | `./data` | 应用工作目录，数据库、日志和备份均写入此目录 |
| `backup_enabled` | 否 | `true` | 是否启用 SQLite 数据库备份 |
| `backup_interval` | 否 | `24h` | 数据库备份间隔 |
| `backup_retention_days` | 否 | `7` | 备份保留天数 |

**`[log]`**

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `level` | 否 | `info` | 日志级别 |
| `file_enabled` | 否 | `true` | 是否写入持久化日志文件 |
| `retention_days` | 否 | `7` | 日志保留天数，`0` 表示不自动清理 |

## 本地开发

### 前置依赖

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- npm
- 已运行的 [CLIProxyAPI（CPA）](https://github.com/router-for-me/CLIProxyAPI)

### 本地启动

1. 复制本地配置：

```bash
cp config.example.toml config.toml
```

2. 修改 `config.toml` 配置内容。

3. 安装 Python 依赖：

```bash
uv sync
```

4. 启动后端：

```bash
uv run python -m cpa_usage_keeper -c config.toml
```

5. 在另一个终端安装前端依赖并启动开发服务器：

```bash
npm --prefix ./web ci
npm --prefix ./web run dev -- --host 127.0.0.1
```

6. 构建前端生产产物：

```bash
npm --prefix ./web run build
```

### 测试

运行前端验证：

```bash
make verify
```

## 子路径反代

部署到 `/cpa` 时设置 `base_path = "/cpa"`，并在反向代理中保留该前缀：

```nginx
location /cpa/ {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

## 发布

推送 `v*` 格式的 tag 即可触发 GitHub Actions 自动构建前端、打包并发布到 PyPI：

```bash
git tag v1.2.0
git push origin v1.2.0
```

发布使用 [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)，需要在 PyPI 项目设置中配置 GitHub Actions 为受信发布者，无需在仓库中存储 API Token。
