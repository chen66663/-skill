# platforms/ — 平台适配定义

每个平台的适配规则集中在一个 JSON 里，构建器（`build.py`）读它来渲染 `skills/` 下的单一源。

| 字段 | 说明 |
|---|---|
| `name` | 平台标识，必须与 `skills/` 里 `<!-- @if NAME -->` 用的名字一致 |
| `display_name` | 只在构建日志和 `dist/<平台>/BUILD.json` 里显示 |
| `install_dir` | `build.py --install` 的安装目标，支持 `~` |
| `vars` | 模板变量取值，对应源文件里的 `{{PY}}` |
| `patterns` | 带参占位符取值，对应源文件里的 `{{script:文件名}}` |
| `overlay` | 平台专属文件的目录名，内容按相对路径镜像进 `dist/<平台>/` |

## 占位符

源文件里不写死路径，只写占位符：

````markdown
```bash
{{PY}} {{script:review_export.py}} export.txt --jobs 6
```
````

| 占位符 | workbuddy 取值 | codex 取值 |
|---|---|---|
| `{{PY}}` | `"$PY"`（配套 SKILL.md 里定义的托管 Python 绝对路径） | `python` |
| `{{script:<名>}}` | `"$SK/<名>"` | `scripts/<名>` |

渲染结果：

| 平台 | 结果 |
|---|---|
| workbuddy | `"$PY" "$SK/review_export.py" export.txt --jobs 6` |
| codex | `python scripts/review_export.py export.txt --jobs 6` |

`script` 这个占位符带参数（文件名），所以前缀和后缀都能按平台各自定义——workbuddy 需要一整段
带引号的绝对路径，codex 只需要相对路径。用带参占位符而不是 `{{SK}}` 这类纯前缀变量，是为了避免
「前缀展开后忘记补右引号」这种只在一边爆掉的隐蔽错误。

新增占位符只需在 `patterns` 里加一项 `"名字": ["前缀", "后缀"]`，源文件里就能用 `{{名字:参数}}`。

## overlay

`platforms/<平台>/overlay/` 下的文件按相对路径拷进 `dist/<平台>/`，路径里要带 skill 名：

```
platforms/codex/overlay/schematic-reviewer/agents/openai.yaml
  -> dist/codex/schematic-reviewer/agents/openai.yaml
```

这样同一个平台可以给不同 skill 放不同文件，不需要为"每个 skill 都放"而做隐式约定。

## 新增一个平台

1. 新建 `platforms/<新平台>.json`，填好上表字段；
2. 在 `skills/**/*.md` 里用 `<!-- @if <新平台> -->` 标注差异段落；
3. 需要专属文件就加 `platforms/<新平台>/overlay/<skill>/...`；
4. 跑 `python build.py --platform <新平台> --check` 验证。

差异很小的平台也可以只靠 overlay 差异，源文件里不加任何 `@if`。
