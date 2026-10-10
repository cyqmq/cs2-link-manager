# .cs2pkg 插件包格式规范

`.cs2pkg` 是 cs2-link-manager 的标准分发格式：一个 **zip 归档**，内含
`cs2pkg.json`（包元数据）和一棵镜像服务器布局的文件树。

插件作者打包发布 → 服主 `add --pkg` 一键导入 → 符号链接部署到服务器，
`pack` / `add --pkg` 往返不丢失元数据。

支持两类包：

* **插件包**（默认）：`addons/` 文件树 + `plugin_type`，一个仓库条目 = 一个插件；
* **游戏内容包**（`kind: "content"`）：任意服务器文件（`cfg/`、`overrides/`、
  `gamedata/`、`addons/` …），通过 `roots` 声明安装根，没有 `plugin_type`。

`pack` 还支持把多个仓库插件打包成**一个多插件包**（`cs2lm pack A B --out dir`），
`add --pkg` 会自动按 `plugins` 列表拆分回多个仓库条目。

---

## 一、包结构

```
MyPlugin.cs2pkg
├── cs2pkg.json          # 包元数据（必填）
└── addons/              # 镜像服务器 addons/ 布局的文件树
    └── counterstrikesharp/
        ├── plugins/MyPlugin/
        │   ├── MyPlugin.dll
        │   └── MyPlugin.deps.json
        └── configs/plugins/MyPlugin/MyPlugin.json
```

`addons/` 树可以镜像：

* CounterStrikeSharp 插件：`addons/counterstrikesharp/plugins/<Name>/`
  （以及相关的 `configs/`、`lang/`、`gamedata/`、`shared/`）；
* Metamod 插件：`addons/metamod/` + `addons/<addon>/bin/`。

## 二、cs2pkg.json 字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | 字符串 | 是 | 插件/内容包名（`add --pkg` 省略名称时使用它）。 |
| `version` | 字符串 | 是 | 语义化版本，如 `1.2.3`。 |
| `kind` | 字符串 | 否 | `plugin`（默认）或 `content`（游戏内容包）。 |
| `plugin_type` | 字符串 | 插件包必填 | `css` / `metamod` / `swiftly` / `plugify` / `modsharp`。内容包不需要。 |
| `ini_lines` | 字符串数组 | 插件包必填 | Metamod 插件需要写入 `metaplugins.ini` 的行；CSS 插件为空数组。内容包不需要。 |
| `plugins` | 字符串数组 | 否 | 多插件包里要拆分的插件目录名列表。 |
| `roots` | 对象 | 内容包推荐 | 内容包的安装根映射：包内顶层目录 → 服务器根相对路径。 |
| `requires_frameworks` | 字符串数组 | 否 | 需要的框架 id（如 `["metamod", "css"]`），安装时检查服务器是否已装。 |
| `platform` | 字符串 | 否 | `windows` / `linux` / `all`（默认 `all`）。安装时若与当前主机不匹配会警告。 |
| `author` | 字符串 | 否 | 作者。 |
| `description` | 字符串 | 否 | 简介。 |
| `category` | 字符串 | 否 | 分类（如 `admin`、`retakes`、`utils`），便于目录搜索与 Web 展示。 |
| `license` | 字符串 | 否 | 许可证。 |
| `homepage` | 字符串 | 否 | 主页。 |
| `repository` | 字符串 | 否 | 源码仓库。 |
| `dependencies` | 对象 | 否 | 程序集级依赖，`{程序集名: 版本约束}`。 |
| `requires` | 字符串数组 或 对象 | 否 | 插件级依赖（见下文）。 |
| `api_version` | 整数 | 否 | 插件 API 版本（仅冗余，权威值在包内 `manifest.json`）。 |
| `entry` | 字符串 | 否 | 插件入口（仅冗余，权威值在包内 `manifest.json`）。 |

最小插件包示例：

```json
{
  "name": "MyPlugin",
  "version": "1.0.0",
  "plugin_type": "css",
  "ini_lines": []
}
```

最小内容包示例：

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

命令行设置这些字段：

* `cs2lm pack MyPlugin --out releases/ --description "..." --category "retakes"`
  把 `description` / `category` 写进 cs2pkg.json（覆盖 manifest 里的值）；
* `cs2lm add MyPlugin path/ --description "..." --category "admin"` 在导入时直接
  写入 manifest（即使包本身没有 cs2pkg.json）；
* `cs2lm registry add Name url --description "..." --category "utils"` 写进
  本地注册表条目。

`roots` 的值是**服务器根相对路径**（相对 `<server>/game`）：

* `"cfg": "game/csgo/cfg"` → 包内 `cfg/xxx` 安装到 `<server>/game/csgo/cfg/xxx`；
* `"game": "game"` → 包内 `game/csgo/...` 安装到 `<server>/game/csgo/...`（用于
  `gameinfo.gi` 等位于 csgo 根的文件）。

未声明 `roots` 时，内容包的每个顶层目录默认映射到 `game/csgo/<目录名>`，
`game/` 目录映射到 `game`。内容包**不能**包含框架核心文件（CSS 的
`api/`/`bin/`/`dotnet/`、Metamod 的 `bin/`/`.vdf`/`metaplugins.ini` 等），
导入时会拒绝。

## 三、插件级依赖（requires）

`requires` 声明**本插件依赖的其他仓库插件**，可以是：

* 插件名列表（旧格式）：`["SharedLib"]`
* 插件 ID → 版本范围的对象（index.json 规范格式）：
  `{ "SharedLib": ">=1.0.0" }`

安装时工具会先自动安装这些依赖；依赖不在仓库里会报错并提示先添加。

## 四、多插件包（plugins）

当 zip 内 `plugins/` 下有多个插件目录时（例如 SimpleAdmin 的 Release 包含
SimpleAdmin + FunCommands + StealthModule 三个插件目录），在 `plugins` 里声明
要拆分的目录名，`add --pkg` 会自动拆成多个仓库条目（一个仓库条目 = 一个插件）：

```json
{
  "name": "SimpleAdmin",
  "version": "1.0.0",
  "plugin_type": "css",
  "plugins": ["SimpleAdmin", "FunCommands", "StealthModule"]
}
```

拆分规则：

* 每个插件得到独立的 `plugins/<Name>`、`configs/plugins/<Name>`、
  `configs/<Name>.*`、`lang/<Name>`、`gamedata/<Name>` 目录副本；
* 包里的 `shared/` 目录**不会**被复制进拆分结果（多个拆分插件若都安装
  `shared/` 下的同一路径，会产生链接冲突）。遇到含 `shared/` 的包时工具会
  打印警告，需要 `shared/` 的服主请手动放置；
* **单插件包不受影响**：`add` 会整棵复制 `addons/`（含 `shared/`），并把
  `shared/<Lib>` 自动链接到服务器（如 cs2-retakes 的
  `shared/RetakesPluginShared`）；
* 拆分出的每个插件独立安装 / 卸载 / 更新。

只有单个插件时无需声明 `plugins`。

### 多插件打包（pack A B C）

`cs2lm pack PluginA PluginB --out releases/` 会把多个仓库插件合并成一个
多插件 `.cs2pkg`：

```json
{
  "name": "plugins",
  "version": "1.0.0",
  "plugin_type": "css",
  "plugins": ["PluginA", "PluginB"]
}
```

* `plugins` 列出包内所有插件目录名，`add --pkg` 导入时会按第四节规则拆回；
* `requires` / `dependencies` **不会**在多插件包里合并（依赖是插件级的），
  需要依赖的插件请分别发布单插件包或在包内用 `manifest.json` 声明；
* 单插件 `pack` 行为不变（不写 `plugins` 字段）。

## 五、游戏内容包（kind: content）

游戏内容 mod（如 CS2-Bot-Improver 这类全家桶）没有插件清单，也不属于单一框架。
它们包含 `cfg/`、`overrides/`、`gamedata/`、`addons/` 甚至 `gameinfo.gi` 等
任意服务器文件。以 `kind: "content"` 打包后可被 cs2-link-manager 管理：

* `add --pkg file.cs2pkg` 导入仓库（`list` 显示类型为 `content`）；
* `install` 把文件**复制**到服务器（不是符号链接），服务器运行时的修改不会
  污染仓库副本；`uninstall` 把复制过去的文件移到仓库 `trash/`；
* `requires_frameworks` 声明需要的框架，安装时若服务器缺失会拒绝（`--force`
  可绕过）；
* `platform` 声明目标平台（`windows`/`linux`/`all`），与当前主机不匹配时
  安装/导入会警告；
* `install --components cfg,addons` 可只安装部分根目录（按 `roots` 的键名
  选择），未指定时安装全部；
* `pack` 导出内容包时按 `roots` 恢复包内顶层布局（`cfg/`、`overrides/` …）。

内容包**不接受**框架核心文件（CSS `api/`/`bin/`/`dotnet/`、Metamod
`bin/`/`.vdf`/`metaplugins.ini`、`gamedata.json`），导入时拒绝。

## 六、与 manifest.json / index.json 的关系

三种文件各司其职：

| 文件 | 角色 | 位置 |
| --- | --- | --- |
| `index.json` | 远端索引：插件最新版本表 + 下载地址 + sha256 | 插件源的固定 URL |
| `.cs2pkg` / zip | 分发载体 | GitHub Release 资产 |
| 包内 `manifest.json` | 权威身份声明：`id` / `version` / `entry` / `api_version` | zip 解压后的 `addons/.../plugins/<Name>/` 内 |

约定：

* 插件仓库的 CI 在发布时读取每个插件的 `manifest.json`，计算 zip 的
  `sha256` / `size`，写入 `index.json`；
* `index.json` 里 `id`、`version`、`entry`、`api_version` 是**冗余**，权威值
  以 zip 内 `manifest.json` 为准；
* 安装 / 更新时，cs2-link-manager 会校验 zip 内 `manifest.json` 的 `id` /
  `version` 与 `index.json` 条目一致，不一致则拒绝；
* 未更新的插件可以继续指回旧 Release 的 zip，实现增量发布。

## 七、版本与校验

* `version` 遵循 SemVer 2.0；`add` 时会尝试从 `<Name>.deps.json` 的
  `targets` 里自动提取 `<Name>/<version>` 作为默认版本（如 `Retakes/3.1.1`），
  提取不到才回退 `1.0.0`；
* `add --pkg` / `pack` 往返时，`version` 与 `requires` 等元数据完整保留。