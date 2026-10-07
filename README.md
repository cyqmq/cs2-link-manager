# cs2-link-manager

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
[![CI](https://github.com/cyqmq/cs2-link-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/cyqmq/cs2-link-manager/actions/workflows/ci.yml)

跨平台 CLI 工具，用于管理 CS2 的 **CounterStrikeSharp** 与 **Metamod** 插件：
把插件文件保存在中央 **repository**（仓库）中，再用 **符号链接**（Windows
上使用 junction，失败时回退到复制）映射到服务器目录。

```
┌─────────────── plugins-repo ───────────────┐        ┌─────────────── cs2-server ──────────────┐
│ plugins/<Name>/                              │        │ game/csgo/addons/...                    │
│   manifest.json   (files + targets + links) │  link  │ counterstrikesharp/plugins/<Name>  ─────┼──▶ repo
│   files/addons/... (real plugin files)      │ ─────▶ │ counterstrikesharp/configs/plugins/<Name>│
└─────────────────────────────────────────────┘        └──────────────────────────────────────────┘
```

插件加载器只会看到符号链接指向的目录，因此服务器的行为与插件文件被直接复制
过去完全一致。卸载时只删除链接——仓库中的副本永远不会被改动。

## 为什么这样做？

* **无卸载残留** — 卸载只删除本工具创建的内容。
* **快速切换插件组合** — profile 可以整体启用/禁用一组插件。
* **抗 CS2 更新** — 插件文件位于 `game/` 之外，不会被更新覆盖。
* **可回滚** — 仓库文件不可变；重新安装 = 重新链接。

## 环境要求

* Python **3.11+**（仅标准库）。
* Linux（首选）或 Windows（支持 junction / 复制回退）。
* 已安装 Metamod:Source 与 CounterStrikeSharp 的 CS2 专用服务器（本工具
  **不安装**核心框架）。

## 安装

```bash
git clone https://github.com/cyqmq/cs2-link-manager.git
cd cs2-link-manager
pip install .
# 开发模式：
pip install -e ".[dev]"
```

安装后会提供 `cs2lm` 命令。也可以不安装直接运行：

```bash
python -m cs2lm --help
```

## 快速开始

```bash
# 1. 初始化仓库（repo 和 server 路径保存在 config.json）
cs2lm init --repo ./plugins-repo --server ./cs2-server

# 2. 添加插件包（包含 addons/ 树的目录，或插件目录）
cs2lm add MyPlugin ./downloads/MyPlugin/

# 3. 安装（在服务器中创建符号链接）
cs2lm install MyPlugin

# 4. 验证
cs2lm list
cs2lm doctor

# 5. 卸载（保留仓库副本）
cs2lm uninstall MyPlugin

# 6. Profile 切换
cs2lm profile create competitive MatchZy SimpleAdmin
cs2lm profile use competitive
```

## 命令参考

| 命令 | 说明 |
| --- | --- |
| `init --server <dir>` | 创建仓库骨架和 `config.json`。 |
| `add <name> <path>` / `add <name> --url <zip-url>` / `add [<name>] --pkg <file.cs2pkg>` | 把插件包（本地目录、下载的 zip 或 `.cs2pkg`）复制进仓库，生成 `manifest.json`；`--pkg` 省略名字时用 `cs2pkg.json` 的 `name`。 |
| `pack <name> [--out <dir>]` | 把仓库插件打包成 `.cs2pkg` 文件。 |
| `install <name>` | 按 manifest 创建链接（幂等）。 |
| `uninstall <name>` | 删除工具创建的链接，保留仓库文件。 |
| `enable <name>` / `disable <name>` | 创建/删除链接（同 install/uninstall）。 |
| `list` | 显示名称、类型、版本、启用/安装状态。 |
| `profile create <name> [plugins...]` | 创建命名 profile。 |
| `profile use <name>` | 启用 profile 内插件、禁用其余插件，并打印差异报告。 |
| `profile list` / `profile delete <name>` | 列出 / 删除 profile。 |
| `doctor` | 检查服务器结构、断链、缺失目标、权限、冲突、CSS API 版本依赖。 |
| `import <name> <path-in-server>` | 把服务器上指定路径的单个插件反向导入仓库。 |
| `adopt [--plugin <name>]` | 扫描服务器上已有的 CSS 插件，批量导入仓库。 |
| `web [--host H] [--port P] [--auth-token T]` | 启动本地 Web UI，浏览并切换插件；设置令牌后需要认证。 |

全局选项：`--repo <path>`（默认 `plugins-repo` 或 `$CS2LM_REPO`）、
`--dry-run`、`--log <file>`、`--log-format text|json`、`--verbose`、
`--version`。

### `--dry-run`

所有写命令都支持 `--dry-run`：只打印将要执行的动作，不改变任何内容。

```bash
cs2lm --repo ./plugins-repo --dry-run install MyPlugin
```

### Profile 切换与差异报告

`profile use <name>` 会启用 profile 内的插件、禁用其余插件，并打印差异报告：

```text
Switched to profile 'competitive':
  Enabled: MatchZy, SimpleAdmin
  Disabled: Retakes
```

`Enabled` 表示本次新增/保持启用的插件，`Disabled` 表示被停用的插件。差异报告会精确体现当前安装状态与目标 profile 的差距。

## 工作原理

### Manifest（清单）

仓库中的每个插件都有 `manifest.json`：

```json
{
  "name": "MyPlugin",
  "version": "1.0.0",
  "plugin_type": "css",
  "enabled": true,
  "files": [
    {"source": "files/addons/counterstrikesharp/plugins/MyPlugin/MyPlugin.dll",
     "target": "game/csgo/addons/counterstrikesharp/plugins/MyPlugin/MyPlugin.dll"}
  ],
  "links": [
    {"source": "files/addons/counterstrikesharp/plugins/MyPlugin",
     "target": "game/csgo/addons/counterstrikesharp/plugins/MyPlugin",
     "kind": "symlink-dir"}
  ],
  "ini_lines": []
}
```

* `files` 把仓库中的每个文件映射到目标路径（相对于服务器根目录）。
* `links` 是安装器实际创建的链接——通常每个插件专属目录对应一个目录符号链接
  （`plugins/<Name>`、`configs/plugins/<Name>`、`gamedata/plugins/<Name>` 等）。
* `ini_lines`（仅 Metamod 插件）是要追加到
  `addons/metamod/metaplugins.ini` 的行。

### 状态数据库

* **位置**：`<repo>/state/links.json`。
* **作用**：记录每次 `install`/`enable` 创建的链接（插件、源、目标、类型、
  时间戳）。`uninstall`/`disable` 会移除对应记录——这是工具能精确知道
  该删除什么、并且绝不触碰未管理文件的原因。
* **如果误删**：`uninstall` 没有记录可循，服务器上的链接会残留（manifest
  的 `enabled` 标志仍会被更新）。`doctor` 会把残留链接报告为
  `orphan-link` 警告。干净的恢复方式：删除 `doctor` 列出的残留链接，
  然后重新运行 `cs2lm install <name>` 重建记录。

### 链接类型

| 类型 | 含义 |
| --- | --- |
| `symlink-dir` | 目录符号链接（Linux）/ junction 回退（Windows）。 |
| `symlink-file` | 文件符号链接（用于插件拥有的单个文件）。 |
| `copy` | 普通复制，用于小型 Metamod 配置文件（`.vdf`）。 |

在 Windows 上的策略是：尝试 `os.symlink` → 尝试 junction（`mklink /J`）→
回退到复制，并给出关于 Administrator / 开发者模式要求的清晰警告。

## 冲突与安全规则

* 如果目标已存在，且**不是**本工具创建的链接：
  * 默认：**拒绝**；
  * `--backup`：先询问确认，再把已有内容移动到
    `<server>/.cs2lm-backups/<timestamp>/` 后安装；
  * `--force`：把已有内容移动到备份后**不询问**直接安装——当你明确要
    接管该路径时使用；
  * `--yes`：配合 `--backup` 跳过确认提示（用于脚本/CI）。
* 绝不覆盖未管理文件。
* 绝不删除仓库文件。
* 所有路径都经过校验，确保不会越出服务器根目录。
* 卸载只删除 `state/links.json` 中记录的链接；如果链接已被真实内容替换，
  卸载会拒绝而不是删除数据。
* 试图覆盖核心框架文件的插件（`counterstrikesharp/bin`、`api`、`dotnet`、
  `gamedata/gamedata.json`、`metamod/bin`、`metamod.vdf` 等）会在 `add`
  阶段被拒绝。

## Windows 说明

* 创建**真正的符号链接**需要 `SeCreateSymbolicLinkPrivilege` 权限，
  通常意味着以**管理员**身份运行，或启用**开发者模式**（Windows 10 1703+，
  设置 → 隐私和安全性 → 开发者选项）。
* **目录 junction**（`mklink /J`）**不需要**管理员或开发者模式——任何
  用户都能在 NTFS 卷上创建。junction 仅适用于目录。创建目录符号链接失败
  时，工具会自动回退到 junction。
* **复制回退**在符号链接和 junction 都失败时使用。常见原因：
  * 目标位于非 NTFS 文件系统（FAT32/exFAT、某些网络共享）；
  * 目标是单个文件而不是目录（junction 不能链接文件）；
  * 父目录不可写。
  你会看到清晰的警告，说明实际使用了哪种模式以及原因。
* 复制模式下安装/卸载仍然正常工作；唯一区别是插件更新需要重新安装
  （副本不会自动保持同步）。
* 插件目录（`plugins/<Name>`、`configs/plugins/<Name>`、`lang/<Name>`、
  `gamedata/plugins/<Name>`）都是目录，因此 junction 回退可以覆盖
  常见场景。

## 各路径的链接策略

工具按路径决定如何把插件文件链接进服务器。核心框架路径绝不会被触碰。

| 路径（相对 `game/csgo/`） | 策略 | 原因 |
| --- | --- | --- |
| `addons/counterstrikesharp/plugins/<Name>/` | **symlink**（Windows 用 junction） | CSS 会枚举该目录，符号链接目录对 .NET 透明 |
| `addons/counterstrikesharp/configs/plugins/<Name>/` | **symlink**（Windows 用 junction） | 插件专属配置目录 |
| `addons/counterstrikesharp/lang/<Name>/` | **symlink**（Windows 用 junction） | 插件专属翻译 |
| `addons/counterstrikesharp/gamedata/plugins/<Name>/` | **symlink**（Windows 用 junction） | 插件专属 gamedata 子目录 |
| `addons/counterstrikesharp/gamedata/gamedata.json` | **不管理** | 框架共享文件；需手动合并 |
| `addons/counterstrikesharp/api`、`bin`、`dotnet`、`shared` | **不管理** | CSS 核心框架 |
| `addons/metamod/bin/` | **不管理** | Metamod 原生二进制（`.so`/`.dll`） |
| `addons/metamod/*.vdf`（第三方插件） | **copy + backup + rollback** | 加载器文件对符号链接敏感 |
| `addons/metamod/metaplugins.ini` | **行编辑 + backup + rollback** | 就地编辑的小文本文件 |
| `addons/<metamod-plugin>/`（插件二进制） | **symlink**（Windows 上复制回退） | 第三方 Metamod 插件目录 |
| `addons/metamod.vdf`、`addons/metamod_x64.vdf` | **不管理** | Metamod 核心加载器文件 |
| `game/csgo/gameinfo.gi` | **不管理** | 引擎配置；Metamod 从这里加载 |

**本工具不管理 Metamod/CSS 核心框架。** 请手动安装（参见
[CounterStrikeSharp 文档](https://docs.cssharp.dev/) 和
[Metamod:Source 安装指南](https://wiki.alliedmods.net/Installing_metamod:source)）。
这是有意为之：核心文件包含原生二进制和加载器 `.vdf`，对符号链接很敏感——
加载链依赖引擎如何解析 `gameinfo.gi` 的搜索路径，Metamod 曾因引擎更新而
失效（参见 [metamod-source issue #232](https://github.com/alliedmodders/metamod-source/issues/232)）。

## Metamod 处理（重要）

* 第三方 **Metamod 插件**：
  * `addons/metamod/` 中的 `.vdf` 文件按 **复制** 方式管理（失败时
    backup + rollback）；
  * `metaplugins.ini` 的编辑带备份，失败时回滚；
  * 插件二进制目录（`addons/<pluginname>/`）使用符号链接
    （Windows 上 junction/复制回退）。

## 从 URL 添加插件

```bash
cs2lm add MyPlugin --url https://example.com/MyPlugin.zip
```

工具会下载 zip、解压、定位包根目录（`addons/` 树或单个包装目录）、自动
识别插件类型并生成清单。zip 不会存入仓库——只复制解压后的插件文件。

## CSS API 依赖检查

当 CSS 插件在其 `.deps.json` 中声明 `CounterStrikeSharp.API` 版本时，该
版本会记录进 manifest，`doctor` 会在与已安装 API 不匹配时发出警告：

* `api-version-mismatch` — 服务器的 `CounterStrikeSharp.API` 版本与插件声明
  的不同。
* `api-version-unverifiable` — 插件声明了依赖，但无法自动读取已安装的 API
  版本；请手动核对。

API 版本直接从
`addons/counterstrikesharp/api/CounterStrikeSharp.API.dll` 读取，使用内置的
小型 ECMA-335 元数据读取器（无第三方依赖）。如果无法解析 DLL，`doctor`
会降级为上面的 unverifiable 警告。

## `.cs2pkg` 插件包格式

`.cs2pkg` 是一个 zip 归档，用于标准化插件分发：

* `cs2pkg.json` — 包元数据（name、version、plugin_type、ini_lines）；
* 插件文件树（镜像服务器布局的 `addons/` 树）。

`cs2pkg.json` 的最小示例：

```json
{
  "name": "MyPlugin",
  "version": "1.0.0",
  "plugin_type": "css",
  "ini_lines": []
}
```

文件树放在与 `cs2pkg.json` 同目录下的 `addons/` 里。插件作者可以直接照此
结构打包发布。

插件作者可以发布 `.cs2pkg` 文件，服主安装：

```bash
cs2lm add MyPlugin --pkg ./MyPlugin.cs2pkg
```

省略 `name` 参数时，工具会自动使用 `cs2pkg.json` 里的 `name`：

```bash
cs2lm add --pkg ./MyPlugin.cs2pkg   # 等效于上面那条命令
```

仓库中的插件也可以导出为该格式：

```bash
cs2lm pack MyPlugin --out ./releases/
# -> releases/MyPlugin.cs2pkg
```

该格式复用了现有的 manifest/链接生成流程：`add --pkg` 之后，插件会被存储
在仓库中，并像其他插件一样用符号链接管理。

**关于插件目录名**：`add` 时提供的名称就是仓库名和服务器上的插件目录名。
即使包内部目录叫别的名字（例如 zip 里是 `DemoPlugin`，你写成
`cs2lm add Renamed ./DemoPlugin/`），工具也会把插件目录统一重命名为
`Renamed`，保证安装/卸载/profile 切换不会错乱。

## 接管已有插件（adopt）

`import` 与 `adopt` 的区别：`import` 处理服务器上**指定路径**的单个插件；
`adopt` 会**扫描整个服务器**，批量导入所有 CSS 插件。当你明确知道插件
所在位置时用 `import`；想一次性接管现有服务器时用 `adopt`。

如果服务器上已经有其他管理器（或手动）安装的插件，`adopt` 会把它们复制进
仓库，之后你就可以统一用符号链接和 profile 管理——工具充当"落地层"：

```bash
cs2lm adopt
# Adopted 3 plugin(s): MatchZy, SimpleAdmin, Retakes
# The original plugin files are still on the server.
# Take over each plugin with:
#   cs2lm install <name> --backup
```

复制过程中原文件会保留，不会被破坏。想不手动清理就接管插件，可以用
`--backup` 安装——旧文件会被移动到
`<server>/.cs2lm-backups/<timestamp>/`，插件则从仓库链接：

```bash
cs2lm install MatchZy --backup
cs2lm install SimpleAdmin --backup
```

使用 `--plugin <name>` 只接管单个插件。已在仓库中的插件会跳过。

如果服务器上某个插件目录是**符号链接**（例如已经被本工具或其他仓库管理），
`adopt` 会跳过它并提示，而不会解析到仓库外部或中断整个扫描。

`import` 遇到符号链接路径时会拒绝并给出明确提示（该路径可能已被本工具或
其他仓库管理）——请先删除符号链接，再指向真实的插件目录重试。

## Web UI

为喜欢用浏览器的服主提供了一个小型可读写 Web 界面：

```bash
cs2lm web --port 8080
# cs2-link-manager Web UI at http://127.0.0.1:8080/  (Ctrl+C to stop)
```

页面列出插件（名称、类型、版本、启用状态、安装状态）并提供启用/禁用按钮。
**安全提示**：默认绑定 `127.0.0.1` 且没有认证——不要把端口暴露到不可信
网络。如果需要在远程机器上使用，请通过 SSH 端口转发访问：

```bash
ssh -L 8080:127.0.0.1:8080 user@server-host
# 然后在本地打开 http://127.0.0.1:8080/
```

绑定非回环地址（`--host 0.0.0.0` 等）时工具会打印警告。需要基础认证时，
用 `--auth-token` 设置共享令牌：

```bash
cs2lm web --host 0.0.0.0 --port 8080 --auth-token my-secret
# 访问 http://<host>:8080/?token=my-secret （页面上会显示令牌输入框）
```

设置了令牌后，所有页面和开关操作都必须携带该令牌。

## 测试

```bash
pip install -e ".[dev]"
pytest
```

测试套件在临时目录中模拟 CS2 服务器——绝不会触碰真实服务器。

## 已知限制

* `add` 期望的插件包是 `addons/` 树或插件目录（根目录含 `.dll` +
  `.deps.json`）。远程 **zip** 通过 `--url` 自动处理，`.cs2pkg` 通过
  `--pkg` 处理；其他本地 zip 文件仍需先手动解压。
* CSS API 版本检查是尽力而为：它读取 `.deps.json` 声明和已安装
  `CounterStrikeSharp.API.dll` 的程序集版本。如果 DLL 无法解析，`doctor`
  会提示手动核对。
* Metamod 插件支持是尽力而为；主要支持的类型是 CounterStrikeSharp。
  在 Windows 上，Metamod 插件和 CSS 插件都是 `.dll` 文件，`classify_plugin`
  无法仅凭扩展名区分——单文件 `.dll` 默认按 CSS 处理，Metamod 插件请提供
  `addons/` 树或 `.vdf` 文件（这两种结构会被正确识别为 Metamod）。
* `gamedata/gamedata.json` 无法管理（框架共享文件）；此类改动请手动合并。
* 插件目录中运行时写入的文件（例如插件生成的配置）在使用符号链接时会
  保留在仓库副本中；使用复制回退时，会随副本一起被删除。

## 项目布局

```
cs2-link-manager/
  src/cs2lm/        # CLI、安装器、manifest、profile、doctor 等
  docs/research.md   # 研究笔记与决策
  tests/             # pytest 测试套件（单元 + 集成）
  examples/          # 示例 profile 和演示插件包
  pyproject.toml
  README.md
  CONTRIBUTING.md
  CHANGELOG.md
```

## 参与贡献

开发环境搭建、测试说明和 PR 指南请参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

MIT