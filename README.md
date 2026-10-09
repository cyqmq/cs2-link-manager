# cs2-link-manager

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
[![CI](https://github.com/cyqmq/cs2-link-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/cyqmq/cs2-link-manager/actions/workflows/ci.yml)

跨平台 CLI 工具，用于管理 CS2 的多框架插件：**Metamod:Source**、
**CounterStrikeSharp (CS#)**、**SwiftlyS2**、**Plugify** 与 **ModSharp**。
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
* 已安装目标插件对应框架（Metamod:Source、CounterStrikeSharp、SwiftlyS2、
  Plugify 或 ModSharp）的 CS2 专用服务器（本工具**不安装**核心框架）。
  安装插件时工具会检测服务器是否已装对应框架，缺失则拒绝（`--force`
  可绕过）。

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
| `add <name> <path>` / `add <name> --url <zip-url> [--addons-subdir <dir>]` / `add [<name>] --pkg <file.cs2pkg>` | 把插件包（本地目录、下载的 zip 或 `.cs2pkg`）复制进仓库，生成 `manifest.json`；`--pkg` 省略名字时用 `cs2pkg.json` 的 `name`；`--addons-subdir` 指定 zip 内 `addons/` 树所在的子目录（如 `public`）；`--type css|metamod|swiftly|plugify|modsharp` 可跳过自动识别。传 `.cs2pkg` 路径给 `add <name> <path>` 会提示改用 `--pkg`；包内没有 `manifest.json`/`cs2pkg.json` 时版本默认 `1.0.0` 并打印警告（可用 `--version` 指定）；包看起来不像插件（无 addons/ 树或二进制）时也会警告。 |
| `pack <name> [<name> ...] [--name <label>] [--out <dir>]` | 把仓库插件打包成 `.cs2pkg` 文件；传多个名字（空格或逗号分隔）会打成**多插件包**。 |
| `install <name|#N> [--from-registry] [--timeout <s>] [--force]` | 按 manifest 创建链接（幂等）；如果插件不在仓库里，自动回退到已配置的 `index.json` 源（或本地注册表）下载安装，并递归补装 `requires` 依赖；`#N` 直接引用 `search` 结果快照里的序号。安装前检测插件所属框架是否已装在服务器上，缺失则拒绝（`--force` 绕过）。 |
| `uninstall <name>` | 删除工具创建的链接，保留仓库文件。 |
| `enable <name> [--force]` / `disable <name> [--force]` | 创建/删除链接（同 install/uninstall）；`--force` 与 `install --force` 一致，可绕过框架检测。 |
| `remove <name>` | 从仓库删除插件（先卸载，再连同 manifest 移到 `trash/plugins/<name>-<时间戳>`），可用 `trash restore` 恢复。 |
| `trash list` / `trash restore <name>` | 列出回收站中的插件 / 把最新一份同名插件恢复到仓库。 |
| `list` | 显示名称、类型、版本、启用/安装状态。 |
| `registry add <name> <url> [--description] [--type] [--addons-subdir] [--sha256 <hex>] [--requires <names>]` | 往本地注册表添加一个插件源（URL）；`--sha256` 记录 zip 校验和，`--requires` 记录依赖插件（逗号分隔）。添加时会做一次 HEAD 可达性探测，不可达会打印警告但照常保存。 |
| `registry list` / `registry remove <name>` | 列出 / 删除注册表条目。 |
| `search [<query>] [--source <url>] [--timeout <s>]` | 合并所有已配置 `index.json` 源 + 本地注册表，输出带序号的目录（名称/版本/状态/来源/描述），并把结果快照写入 `state/search_result.json` 供 `install #N` 引用。状态区分「已装(版本)」（已链接到服务器）与「仓库(版本,未链接)」（仅存在于仓库，尚未启用）。 |
| `update [name...] [--yes] [--force] [--remove-orphans] [--timeout <s>] [--self]` | 拉取配置的多个 `index.json` 源，只更新**本地已安装**的插件；缺失插件**不列出、绝不自动装**（避免大源刷屏）；`--force` 可绕过更新时的框架检测；`--remove-orphans` 把不在任何源里的插件移到仓库 trash；`--self` 尝试更新工具自身（git 检出时执行 `git pull`）。 |
| `source add <index-url> [--name <n>] [--header "K: V"]...` | 添加一个 `index.json` 插件源（可带鉴权 header）；添加前会先抓取并校验 `index.json`（schema + plugins 对象），无效/不可达会拒绝添加。 |
| `source list` / `source remove <index-url>` / `source clear` | 列出 / 删除 / 清空插件源。 |
| `profile create <name> [plugins...]` | 创建命名 profile。 |
| `profile use <name>` | 启用 profile 内插件、禁用其余插件，并打印差异报告。 |
| `profile list` / `profile delete <name>` | 列出 / 删除 profile。 |
| `doctor [--verbose]` | 检查服务器结构、断链、缺失目标、权限、冲突、CSS API 版本依赖；`--verbose` 额外输出各框架在服务器上的安装状态。 |
| `import <name> <path-in-server>` | 把服务器上指定路径的单个插件反向导入仓库。 |
| `adopt [--plugin <name>]` | 扫描服务器上已有的 CSS 插件，批量导入仓库。 |
| `web [--host H] [--port P] [--auth-token T] [--daemon] [--pidfile F] [--daemon-log F]` | 启动本地 Web 管理界面：状态卡显示服务器框架，支持目录搜索、一键安装/卸载、更新全部、插件启停；并暴露 JSON API（见「Web UI」）。`--port 0` 分配随机空闲端口并在启动行/`CS2LM_READY` 打印**实际**端口；`--daemon` 后台化，父进程会等待子进程真正监听成功才返回（失败返回非零并给出原因）。设置令牌后需要认证。 |

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
| `addons/swiftly/plugins/<Name>/`、`configs/plugins/<Name>/` | **symlink**（Windows 用 junction） | SwiftlyS2 插件目录与配置 |
| `addons/plugify/plugins/<Name>/`、`configs/plugins/<Name>/` | **symlink**（Windows 用 junction） | Plugify 插件目录与配置 |
| `addons/modsharp/plugins/<Name>/`、`configs/plugins/<Name>/` | **symlink**（Windows 用 junction） | ModSharp 插件目录与配置 |
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

## 多框架支持与框架检测

支持以下插件框架（`plugin_type` 可写规范 id 或别名）：

| 框架 | `plugin_type` | 别名 | 服务器目录（相对 `game/csgo/`） |
| --- | --- | --- | --- |
| Metamod:Source | `metamod` | `metamod-source`, `mm` | `addons/metamod` |
| CounterStrikeSharp (CS#) | `css` | `counterstrikesharp`, `cs#` | `addons/counterstrikesharp` |
| SwiftlyS2 | `swiftly` | `swiftly-s2` | `addons/swiftly` |
| Plugify | `plugify` | `plugify-s2` | `addons/plugify` |
| ModSharp | `modsharp` | `mod-sharp` | `addons/modsharp` |

* `add` / `import` / `registry add` 的 `--type` 接受上表任意值；不传时自动
  按包内 `addons/` 树的根目录识别框架。
* 服务器端框架检测：工具扫描 `<server>/<csgo_rel>/addons`，报告每个框架
  是否就位。CSS 额外要求 `api/CounterStrikeSharp.API.dll` 存在；
  没有 marker 的框架（swiftly/plugify/modsharp）要求根目录里除了
  `plugins`/`configs` 之外还有框架自身的文件（如 `bin`/core），否则视为
  未安装——防止“用 `--force` 装了一个插件后，插件链接创建的 `addons/<fw>/`
  目录被误判为框架已安装”。
* **安装/更新防护**：`install` / `enable` / `update` 时如果插件所属框架未装在
  服务器上，直接拒绝并给出安装框架的路径提示；确认无误可用 `--force` 绕过
  （`update --force` 同样生效）。
* `doctor` 与 `web` 会显示服务器当前已装的框架。

框架检测在 `doctor --verbose`、`web /api/status` 与 Web 页面状态卡中可见。

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

**GitHub 源码 zip**：很多插件发布的是源码 zip，编译产物不在根目录，而是
嵌套在 `public/addons`、`.Compiled/addons`、`release/addons` 等子目录里。
工具会**递归查找 `addons/` 树**（限制深度 5），自动把该子目录当作包根目录。
如果自动查找没命中，可以显式指定：

```bash
# zip 解压后是 repo/public/addons/...，就指到 public
cs2lm add MyPlugin --url https://github.com/user/plugin/archive/refs/heads/main.zip \
  --addons-subdir public
```

`--addons-subdir` 指向**包含 `addons/` 树的那一层目录**（不是 `addons` 本身；
直接传 `public/addons` 也会被归一化到 `public`）。

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

`.cs2pkg` 是一个 zip 归档，用于标准化插件分发（完整格式规范见
`docs/format.md`）：

* `cs2pkg.json` — 包元数据（name、version、plugin_type、ini_lines，以及可选的
  author/description/license/homepage/repository/dependencies/plugins）；
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

**游戏内容包**（`kind: "content"`）不需要 `plugin_type`/`ini_lines`，它管理
任意服务器文件（`cfg/`、`overrides/`、`gamedata/`、`addons/` …）并用 `roots`
声明安装根：

```json
{
  "kind": "content",
  "name": "BotImprover",
  "version": "1.4.5",
  "roots": {
    "addons": "game/csgo/addons",
    "cfg": "game/csgo/cfg",
    "overrides": "game/csgo/overrides"
  },
  "requires_frameworks": ["metamod", "css"],
  "platform": "windows"
}
```

内容包以**复制**方式安装到服务器（不是符号链接），`uninstall` 会把复制文件
移入仓库 `trash/`；`requires_frameworks` 缺失时安装会被拒绝（`--force` 可
绕过）；`platform` 与当前主机不匹配时导入/安装会警告。

可选元数据（`pack` 时从 manifest 自动写入，`add --pkg` 时写回 manifest，
保证发布往返不丢失信息）：

```json
{
  "name": "MyPlugin",
  "version": "1.0.0",
  "plugin_type": "css",
  "author": "Alice",
  "description": "A competitive config plugin",
  "license": "MIT",
  "homepage": "https://example.com",
  "repository": "https://github.com/example/myplugin",
  "dependencies": { "CounterStrikeSharp.API": "1.0.376" },
  "requires": ["SharedLib"],
  "plugins": ["MyPlugin", "MyPluginExtra"],
  "ini_lines": []
}
```

`requires` 是本插件的**插件级依赖**列表（别的仓库插件名），安装时工具会先
自动安装这些依赖；若依赖不在仓库里则报错。禁用被其他已启用插件依赖的插件
也会被拒绝。

`plugins` 用于**多插件包**：当包里 `plugins/` 下有多个插件目录时，声明
`plugins` 列表让 `add --pkg` 自动拆成多个仓库条目（每个条目一个插件）。
只有一个插件时无需声明。

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

**关于版本号**：`add` 会尝试从 `<Name>.deps.json` 的 `targets` 里自动提取
`<Name>/<version>` 作为默认版本（例如 cs2-retakes 的 `Retakes/3.1.1`），
提取不到才回退 `1.0.0`；`pack` 时该版本原样写回 `cs2pkg.json`。

**多插件包支持拆分**：如果包里 `plugins/` 下有多个插件目录（例如 SimpleAdmin
的 Release 包含主插件 + FunCommands + StealthModule 三个插件目录），
`cs2lm` 默认会报错并列出目录。此时可以用 `--plugins` 显式声明插件目录名，
工具会把包拆成多个仓库条目（一个仓库条目 = 一个插件）：

```bash
# 从 URL 添加多插件包：拆成 3 个独立仓库条目
cs2lm add --url https://github.com/x/SimpleAdmin/releases/download/v1.0/SimpleAdmin.zip \
  --plugins SimpleAdmin,FunCommands,StealthModule

# 本地目录同样支持
cs2lm add --plugins SimpleAdmin,FunCommands,StealthModule ./SimpleAdmin/

# .cs2pkg 包可以在 cs2pkg.json 里声明 plugins 字段，add --pkg 自动拆分
cs2lm add --pkg ./SimpleAdmin.cs2pkg
```

拆分会按插件名切分各自的 `plugins/<Name>`、`configs/plugins/<Name>`、
`lang/<Name>`、`gamedata/<Name>` 等目录，每个插件独立安装/卸载/更新。
若包里含 `shared/` 目录，工具会打印警告并**不**把它复制进拆分结果
（多个拆分插件安装同一 `shared/` 路径会产生链接冲突）。

**单插件包自带 `shared/` 则完全支持**：`add` 会整棵复制 `addons/`（含
`shared/`），并自动把 `shared/<Lib>` 链接到服务器的
`addons/counterstrikesharp/shared/<Lib>`。cs2-retakes 这类依赖
`shared/RetakesPluginShared` 的插件可以直接托管。
注册表条目也可以用 `--plugins` 声明多插件包：

```bash
cs2lm registry add SimpleAdmin https://.../SimpleAdmin.zip \
  --plugins SimpleAdmin,FunCommands,StealthModule
cs2lm install SimpleAdmin --from-registry   # 添加全部 3 个，安装 SimpleAdmin
```

**多插件打包**：仓库里的多个插件可以导出成一个 `.cs2pkg`，`add --pkg` 再拆回：

```bash
cs2lm pack Alpha Beta --out ./releases/
# -> releases/plugins.cs2pkg（cs2pkg.json 声明 plugins: ["Alpha", "Beta"]）

cs2lm add --pkg ./releases/plugins.cs2pkg   # 在别的仓库里拆回 Alpha、Beta
```

**内容包管理**：把服务器上的 `cfg/`/`overrides/` 等游戏内容打包分发：

```bash
cs2lm add --pkg ./BotImprover.cs2pkg        # 导入内容包（类型显示为 content）
cs2lm install BotImprover                    # 复制文件到服务器
cs2lm install BotImprover --components cfg   # 只安装 cfg 根目录
cs2lm uninstall BotImprover                  # 移除复制文件（进 trash）
cs2lm pack BotImprover --out ./releases/     # 重新导出内容包
```

**文件校验和**：每个纳入管理的文件都会在 manifest 里记录 `sha256`，为后续
的完整性校验/更新比对打基础。

## 浏览目录与按需安装（search / install）

`cs2lm search` 把**所有已配置的 `index.json` 源 + 本地注册表**合并成一个
带序号的统一目录，并标注每个插件在你仓库里的状态：

```text
#  [#]  名称            版本    状态          来源      描述
#  [1]  cs2-retakes     3.1.1   未安装        index-a   retakes插件
#  [2]  MatchZy         1.0.0   已装(1.0.0)   index-b   比赛管理
#  [3]  SimpleAdmin     1.9.0   未安装        registry  ...
```

```bash
# 浏览全部 / 按关键词过滤 / 只看某个源
cs2lm search
cs2lm search retakes
cs2lm search --source https://example.com/index.json

# 结果快照写入 state/search_result.json，install 支持 #N 直接引用
cs2lm install #1

# 或直接按名字装（不在仓库里会自动回退到源）
cs2lm install MatchZy
```

`install` 的解析顺序：

1. `#N` → 读 `state/search_result.json` 快照，按序号定位插件；
2. 插件已在仓库 → 走本地 manifest 安装；
3. 插件不在仓库 → 在合并的 `index.json` 源里找：找到就下载、校验、添加并
   安装，`requires` 依赖会**递归自动补装**；
4. 源里没有 → 回退到本地注册表（`--from-registry` 强制只走这一步）；
5. 都没有 → 报错并提示先 `cs2lm search`。

本地注册表 `registry.json` 仍然可用（适合不发布 index 的零散 zip）：

```bash
# 添加一个插件源（URL 可以是 zip / .cs2pkg / GitHub release）
cs2lm registry add MatchZy https://example.com/MatchZy.zip \
  --description "Match management plugin" --type css

# 一键添加 + 安装（等价于 install 流程的第 4 步回退）
cs2lm install MatchZy --from-registry
```

`install --from-registry` 会从注册表 URL 下载、添加进仓库，然后立即安装。
注册表是纯 JSON，社区可以共享：把 `registry.json` 分发出去，别人直接
`cs2lm registry add` 导入即可。awesome-cs2 等仓库的 manifest 列表可以转换
成这种格式。

### index.json 多源更新（update）

`cs2lm` 只认 `index.json`，不认识 tag / Release。每个插件源提供一个
`index.json`，里面记录该源里每个插件的最高版本和下载地址（完整规范见
`docs/INDEX.md`）。

新建仓库（`cs2lm init`）会**内嵌默认源**
`https://github.com/cyqmq/cs2pkg-port`（社区端口包集合），开箱即用；
它和普通源一样可 `source remove` / `source clear` 移除，清空后不会被重新
注入。老仓库（`sources` 为空且无标记）首次加载会自动补上默认源一次；
已有自定义源的仓库保持不动。

`source add` 也支持直接粘贴 GitHub 仓库页 URL（如
`https://github.com/owner/repo`），会自动解析成
`raw.githubusercontent.com/<owner>/<repo>/<branch>/index.json`（默认
`main`，也可用 `.../tree/<branch>` 指定分支），方便把仓库当源用。

```bash
# 添加插件源（可以是 http/https/file 直链，或 GitHub 仓库页）
cs2lm source add https://example.com/index.json
cs2lm source add https://github.com/owner/plugin-repo

# 私有源带鉴权 header
cs2lm source add https://example.com/private/index.json \
  --header "Authorization: Bearer xxxxx" --name my-repo

# 查看 / 删除源
cs2lm source list
cs2lm source remove https://example.com/index.json

# 只更新本地已安装的插件
cs2lm update

# 只更新指定插件（必须已安装）
cs2lm update MatchZy

# 脚本场景跳过确认 / 干跑
cs2lm update --yes
cs2lm update --dry-run

# 把不在任何源里的插件移到仓库 trash（默认只提示不删除）
cs2lm update --remove-orphans
```

更新流程：

1. 依次拉取每个源的 `index.json`（带 **ETag 缓存**；单源失败跳过，不影响
   其他源；网络挂了用上次缓存兜底）；
2. 按**多源合并规则**得到「每个插件的最高版本 + 下载地址」：每个插件独立
   取最高版本，版本相同时越靠前的源越优先；非 SemVer、缺 `sha256`、
   `yanked: true`、或 `api_version` 不在支持范围内的条目会被跳过并警告；
3. 扫描本地 manifest，对比版本：本地版本低 → **更新**；本地相同或更高 →
   **跳过**；本地缺失 → **不列出、不自动安装**（插件获取统一走
   `search` → `install`，避免大索引刷屏）；
4. 更新时下载 zip → 校验 `sha256`（索引必填，缺失则跳过）→ 解压 →
   校验包内 `manifest.json` 的 `id` / `version` 与索引一致 → **原子替换**
   插件目录（`.<name>.new` → 旧目录改 `.<name>.old` → 新目录就位 → 删 `.old`）；
5. 已安装的插件更新后自动重装链接；每次操作写入 `state/update_log.json`。

`--dry-run` 只报告计划，不修改任何文件。

**api_version 兼容过滤**：在 `config.json` 的 `update.api_version_range` 里
配置客户端支持的 API 版本闭区间（如 `[1, 2]`），合并时自动跳过范围外的条目；
不配置则接受所有版本。

## 插件依赖管理（requires）

插件可以声明依赖其他仓库插件（如共享库）。manifest 里的 `requires` 可以是
插件名列表，也可以是「插件 ID → 版本范围」的对象（index.json 规范）：

```json
{ "name": "MainPlugin", "requires": ["SharedLib"] }
```

```json
{ "id": "MainPlugin", "requires": { "SharedLib": ">=1.0.0" } }
```

行为：

* `cs2lm install MainPlugin` 会**先自动安装** `SharedLib`（递归解析依赖）；
* 依赖不在仓库里但出现在同一 `index.json` 源 → `install` 会从源里**自动补装**；
* 依赖不在任何源里 → 报错并提示先 `search` / `registry add` 添加；
* 依赖循环（A→B→A）→ 报错拒绝；
* `cs2lm uninstall SharedLib` 时，如果 `MainPlugin` 已启用且依赖它，会**拒绝
  卸载**并提示先禁用依赖方；
* `pack` / `add --pkg` / `registry add --requires` 都会保留依赖信息。

这样"插件装上了但缺共享库跑不起来"的问题会在安装阶段就被拦住。

## 校验和与完整性

每个托管文件都在 manifest 里记录了 `sha256`；注册表条目还可以记录整个 zip
的 `sha256`：

```bash
cs2lm registry add MyPlugin https://example.com/MyPlugin.zip \
  --sha256 <zip 的 sha256 十六进制>
```

`install --from-registry` 和 `update` 下载后会先校验 zip 哈希，不匹配直接
拒绝——下载损坏或被替换会立刻发现。公钥签名体系暂不引入：单维护者场景下，
URL + 文件级/zip 级 SHA-256 已覆盖完整性，签名只会增加维护负担。

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

为喜欢用浏览器的服主提供了一个小型可读写 **Web 管理界面**：

```bash
cs2lm web --port 8080
# cs2-link-manager Web UI at http://127.0.0.1:8080/  (Ctrl+C to stop)
# CS2LM_READY port=8080 auth=none
```

页面顶部有**服务器状态卡**（Web 在线、认证状态、CS2 进程是否在运行、
**已安装的插件框架**、仓库路径、服务器路径）。状态卡下方提供：

* **目录搜索** — 输入关键词搜索所有 `index.json` 源 + 本地注册表，带
  状态/来源/描述，每个结果有一键 **Install** 按钮；
* **Update all** — 一键执行 `cs2lm update --yes`；
* **插件表** — 列出仓库插件（名称、类型、版本、启用状态、安装状态），
  提供启用/禁用按钮。

**JSON API**（脚本 / 未来前端可直接使用）：

| 端点 | 说明 |
| --- | --- |
| `GET /api/health` | 就绪检测（见下） |
| `GET /api/status` | 服务器状态 + `frameworks`（各框架是否已装） |
| `GET /api/plugins` | 仓库插件列表 |
| `GET /api/catalog?query=&source=` | 合并目录搜索 |
| `POST /api/install` `{"name": "X"}` | 安装插件（支持 `#N`） |
| `POST /api/uninstall` `{"name": "X"}` | 卸载插件 |
| `POST /api/update` `{"dry_run": true}` | 更新计划 / 执行更新 |

```bash
curl -H "X-Auth-Token: my-secret" http://127.0.0.1:8080/api/status
# {"web": "online", "repo": "...", "server": "...", "cs2": "online",
#  "frameworks": [{"id": "css", "name": "CounterStrikeSharp (CS#)", "installed": true}, ...]}

curl -H "X-Auth-Token: my-secret" -X POST \
  -H "Content-Type: application/json" \
  -d '{"name": "MatchZy"}' \
  http://127.0.0.1:8080/api/install
# {"name": "MatchZy", "messages": ["MatchZy: installed 1.0.0."], "status": "ok"}
```

**就绪检测**：启动时会打印 `CS2LM_READY port=...`，同时提供
`GET /api/health` 端点返回 JSON `{"status": "ok", ...}`——包装脚本可以据此
判断服务**真正开始监听**，而不是只靠 `kill -0` 判断进程存活：

```bash
curl http://127.0.0.1:8080/api/health
# {"status": "ok", "service": "cs2-link-manager-web", ...}
```

* `/api/health` 是**免认证**的就绪探针（即使设置了 `--auth-token` 也不需要
  令牌），方便包装脚本/负载均衡器直接探测；
* 后台化（`--daemon`）时子进程以 `python -u` 启动，stdout 无缓冲，
  `CS2LM_READY port=...` 会**立即写入** `--daemon-log`；
* `--daemon` 父进程会在返回前轮询 `/api/health`（或从日志解析实际端口）确认
  子进程真的在监听；端口被占用/立即退出时返回非零并清理 pidfile，不会误报
  “Started web UI daemon”。

**安全提示**：默认绑定 `127.0.0.1` 且没有认证——不要把端口暴露到不可信
网络。如果需要在远程机器上使用，请通过 SSH 端口转发访问：

```bash
ssh -L 8080:127.0.0.1:8080 user@server-host
# 然后在本地打开 http://127.0.0.1:8080/
```

绑定非回环地址（`--host 0.0.0.0` 等）时**必须**设置 `--auth-token`，否则
命令直接报错退出。需要基础认证时：

```bash
cs2lm web --host 0.0.0.0 --port 8080 --auth-token my-secret
# 访问 http://<host>:8080/?token=my-secret （页面上会显示令牌输入框）
```

设置了令牌后，所有页面和开关操作都必须携带该令牌。脚本/API 调用可以走
`X-Auth-Token` 请求头，无需在 URL 里带令牌：

```bash
curl -H "X-Auth-Token: my-secret" http://127.0.0.1:8080/
curl -X POST -H "X-Auth-Token: my-secret" -d "plugin=MatchZy&action=disable" http://127.0.0.1:8080/toggle
```

### 后台运行（--daemon）

`web` 命令自带跨平台后台运行，不需要在面板脚本里分别写 `nohup` 和
`Start-Process`：

```bash
cs2lm web --host 0.0.0.0 --port 27015 --auth-token my-secret \
  --daemon --pidfile /srv/cs2/web.pid --daemon-log /srv/cs2/web.log
# Started web UI daemon (pidfile /srv/cs2/web.pid).
```

* Linux：子进程以独立 session 后台运行；
* Windows：子进程以 `DETACHED_PROCESS` 分离运行；
* PID 写入 `--pidfile`，stdout/stderr 追加到 `--daemon-log`；
* 收到 `SIGTERM`/`Ctrl+C` 时优雅关闭，不会残留端口占用。

## 与游戏服务器同端口运行（UDP/TCP 共存）

CS2 的服务器流量是 **UDP**，Web UI 是 **TCP**——两种协议互不冲突，可以
让管理面板和游戏服务共用同一个端口号（例如简幻欢面板分配的一个随机端口）：

```bash
# CS2 监听 UDP 27015（游戏流量）
# cs2lm 监听 TCP 27015（管理面板）
cs2lm web --host 0.0.0.0 --port 27015 --auth-token my-secret --daemon
```

`curl http://127.0.0.1:27015/?token=my-secret` 返回管理页面，同时
UDP 27015 上的游戏流量完全不受影响。这是面板场景的核心用法：**不需要
为管理面板额外申请端口**。

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
* 框架目录布局采用各框架官方约定的 `plugins/<Name>` + `configs/plugins/<Name>`
  结构；若某框架后续改变目录约定，请以该框架文档为准。
* CSS API 版本检查是尽力而为：它读取 `.deps.json` 声明和已安装
  `CounterStrikeSharp.API.dll` 的程序集版本。如果 DLL 无法解析，`doctor`
  会提示手动核对。
* 在 Windows 上，Metamod 插件和 CSS 插件都是 `.dll` 文件，`classify_plugin`
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