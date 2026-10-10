# index.json 规范（v1）

`index.json` 是**插件仓库**和 **cs2-link-manager** 之间唯一的契约：

* 插件仓库每次发 Release 后自动生成 / 更新 `index.json`；
* cs2-link-manager 只读 `index.json`，不看 GitHub tag、不看 Release 页面；
* 每个插件源一个 `index.json`，Python 端按源顺序合并。

---

## 一、顶层结构

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `schema` | 整数 | 是 | 规范版本号，当前为 `1`。Python 用它判断能否解析。 |
| `name` | 字符串 | 否 | 源名称，便于日志显示，如 `"official-repo"`。 |
| `generated_at` | 字符串 | 否 | 生成时间，ISO 8601，如 `2026-10-08T12:00:00Z`。 |
| `plugins` | 对象 | 是 | 键为插件 ID，值为插件条目。 |

约定：

* `schema` 必须存在；Python 端不认识的 `schema` 会**跳过整个源**。
* `plugins` 为空对象也合法，表示该源当前没有插件。
* 顶层不要放其他业务数据，保持精简。

示例：

```json
{
  "schema": 1,
  "name": "official-repo",
  "generated_at": "2026-10-08T12:00:00Z",
  "plugins": {
    "hello": { "...": "..." }
  }
}
```

## 二、插件条目字段

每个插件条目描述「该插件在该源里的最高版本」。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | 字符串 | 是 | 插件唯一 ID，必须与 `plugins` 的键一致。 |
| `version` | 字符串 | 是 | SemVer 2.0 版本，如 `1.2.3`、`1.2.3-beta.1`。 |
| `download_url` | 字符串 | 是 | zip 直链（绝对 URL 或相对路径，相对路径基于本 index.json 的 URL 解析）。 |
| `sha256` | 字符串 | 是 | zip 的 SHA-256（安全优先，缺失则跳过该插件）。 |
| `size` | 整数 | 否 | zip 字节数，用于显示进度或预校验。 |
| `api_version` | 整数 | 否 | 插件 API 版本，客户端用它过滤不兼容的版本。 |
| `min_app_version` | 字符串 | 否 | 要求的最低主程序版本。 |
| `entry` | 字符串 | 否 | 入口，如 `hello:Plugin`。仅作冗余，权威值在 zip 内的 `manifest.json`。 |
| `yanked` | 布尔 | 否 | 为 `true` 表示该版本已撤回，不参与选择。 |
| `name` | 字符串 | 否 | 展示名。 |
| `description` | 字符串 | 否 | 简介。 |
| `category` | 字符串 | 否 | 分类（如 `admin`、`retakes`、`utils`），search / Web 目录中展示。 |
| `author` | 字符串 | 否 | 作者。 |
| `homepage` | 字符串 | 否 | 主页。 |
| `tags` | 字符串数组 | 否 | 分类标签。 |
| `requires` | 对象 | 否 | 依赖，键为插件 ID，值为版本范围。 |
| `released_at` | 字符串 | 否 | 该版本发布时间，ISO 8601。 |
| `tag` | 字符串 | 否 | 该资产所在的 Release tag，便于排查，Python 不依赖。 |

示例：

```json
{
  "schema": 1,
  "plugins": {
    "hello": {
      "id": "hello",
      "version": "1.2.3",
      "download_url": "https://github.com/user/repo/releases/download/v1.2.3/hello.zip",
      "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
      "api_version": 1,
      "requires": {
        "shared-lib": ">=1.0.0"
      },
      "description": "A hello plugin",
      "tag": "v1.2.3"
    }
  }
}
```

约定：

* `id` 与键不一致时，**以键为准**并记一条警告。
* `version` 必须符合 SemVer 2.0；不合法时 Python 端跳过该插件并记录日志。
* `download_url` 必须是**直链**（能直接下载 zip），不能是网页地址。相对路径
  会基于本 index.json 的 URL 解析成绝对地址。
* `download_url` 允许指向**旧 tag**，Python 不关心新旧。
* `sha256` 必填；缺失或不是合法的 64 位十六进制时，该插件被跳过并记录警告。
* `yanked: true` 的版本不参与选择。
* 权威的 `id` / `version` / `entry` / `api_version` 以 zip 内 `manifest.json` 为准，
  `index.json` 里的是冗余信息，用于快速对比。

## 三、zip 内 manifest.json

下载的 zip 解压后应包含一个 `manifest.json`（权威身份声明）：

```json
{
  "id": "hello",
  "version": "1.2.3",
  "entry": "hello:Plugin",
  "api_version": 1,
  "requires": {
    "shared-lib": ">=1.0.0"
  }
}
```

cs2-link-manager 在安装/更新时会校验：

* `manifest.json` 的 `id` 与索引一致；
* `manifest.json` 的 `version` 与索引一致。

不一致则拒绝安装。没有 `manifest.json` 的包（如旧的 `.cs2pkg` 格式）跳过校验。

## 四、多源合并语义

Python 端拿多个源的 `index.json`，按下述规则合并：

1. **按插件 ID 分组**：不同源里 `id` 相同的视为同一插件。
2. **取最高版本**：每个插件最终选版本最高的那个条目。
3. **同版本取靠前源**：版本相同时，源顺序越靠前越优先。
4. **单源失败跳过**：某个源拉取失败或 `schema` 不支持，跳过该源，不影响其他源。
5. **字段合并**：以选中的那个条目为准，不做字段级合并，避免冲突。
6. **孤儿判定**：本地有、所有源都没有的插件，视为孤儿，由项目策略决定保留或删除。
7. **不合法条目跳过**：非 SemVer 版本、缺少 `sha256`、`yanked: true`、或
   `api_version` 不在客户端支持范围内的条目，直接跳过并记录警告。

合并后得到一张「每个插件的最终可用版本表」，Python 再拿它跟本地对比。

示例：

| 插件 | 源1 | 源2 | 源3 | 结果 |
| --- | --- | --- | --- | --- |
| `hello` | 1.2.3 | 1.1.0 | 无 | 源1 的 1.2.3 |
| `world` | 无 | 0.4.1 | 0.3.0 | 源2 的 0.4.1 |
| `foo` | 2.0.0 | 2.0.0 | 2.0.0 | 源1 的 2.0.0（同版本取靠前） |
| `bar` | 1.0.0 | 1.5.0 | 1.2.0 | 源2 的 1.5.0 |

## 五、版本规则

* 必须使用 **SemVer 2.0**：`MAJOR.MINOR.PATCH`，可带预发布标识，如 `1.2.3-beta.1`。
* 比较按语义化版本规则，**预发布版本低于同号正式版**（`1.2.3 > 1.2.3-beta`）。
* build 元数据忽略：`1.2.3+build1` 与 `1.2.3+build2` 视为同版本。
* 非 SemVer 版本（如 `latest`、`v1.2`）**跳过该插件并记录日志**，不要用字符串直接比较。
* 插件 ID 里不要包含 `-数字.数字.数字` 这种片段，避免从资产名解析时误判。
* 建议 `id` 只用小写字母、数字、连字符，如 `my-plugin`。
* 版本号一旦发布不要覆盖，同一版本不要重复出现在多个 Release。

## 六、兼容与扩展

* `schema` 是唯一的兼容开关。加字段不升 `schema`，破坏性变更才升。
* 未知字段 Python 端忽略，不要报错，保证向后兼容。
* 需要扩展时，加在插件条目里，加前缀或放进 `extra` 对象里，避免与核心字段冲突：

```json
{
  "id": "hello",
  "version": "1.2.3",
  "download_url": "https://.../hello.zip",
  "extra": { "category": "ui", "icon": "..." }
}
```

* 私有源鉴权信息**不要**放进 `index.json`，放在 Python 项目配置里
  （`cs2lm source add <url> --header "Authorization: Bearer xxx"`）。
* 客户端支持的 `api_version` 范围在 `config.json` 的 `update.api_version_range`
  里配置（如 `[1, 2]`，闭区间）。不在范围内的条目在合并阶段被跳过并记录警告；
  不配置表示接受所有版本。