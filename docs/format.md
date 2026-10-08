# .cs2pkg 插件包格式规范

`.cs2pkg` 是 cs2-link-manager 的标准插件分发格式：一个 **zip 归档**，内含
`cs2pkg.json`（包元数据）和一棵镜像服务器布局的 `addons/` 文件树。

插件作者打包发布 → 服主 `add --pkg` 一键导入 → 符号链接部署到服务器，
`pack` / `add --pkg` 往返不丢失元数据。

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
| `name` | 字符串 | 是 | 插件名（`add --pkg` 省略名称时使用它）。 |
| `version` | 字符串 | 是 | 语义化版本，如 `1.2.3`。 |
| `plugin_type` | 字符串 | 是 | `css` 或 `metamod`。 |
| `ini_lines` | 字符串数组 | 是 | Metamod 插件需要写入 `metaplugins.ini` 的行；CSS 插件为空数组。 |
| `author` | 字符串 | 否 | 作者。 |
| `description` | 字符串 | 否 | 简介。 |
| `license` | 字符串 | 否 | 许可证。 |
| `homepage` | 字符串 | 否 | 主页。 |
| `repository` | 字符串 | 否 | 源码仓库。 |
| `dependencies` | 对象 | 否 | 程序集级依赖，`{程序集名: 版本约束}`。 |
| `requires` | 字符串数组 或 对象 | 否 | 插件级依赖（见下文）。 |
| `plugins` | 字符串数组 | 否 | 多插件包里要拆分的插件目录名列表。 |
| `api_version` | 整数 | 否 | 插件 API 版本（仅冗余，权威值在包内 `manifest.json`）。 |
| `entry` | 字符串 | 否 | 插件入口（仅冗余，权威值在包内 `manifest.json`）。 |

最小示例：

```json
{
  "name": "MyPlugin",
  "version": "1.0.0",
  "plugin_type": "css",
  "ini_lines": []
}
```

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

## 五、与 manifest.json / index.json 的关系

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

## 六、版本与校验

* `version` 遵循 SemVer 2.0；`add` 时会尝试从 `<Name>.deps.json` 的
  `targets` 里自动提取 `<Name>/<version>` 作为默认版本（如 `Retakes/3.1.1`），
  提取不到才回退 `1.0.0`；
* `add --pkg` / `pack` 往返时，`version` 与 `requires` 等元数据完整保留。