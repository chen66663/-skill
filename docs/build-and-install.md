# 构建与安装

本仓库只维护**一份** skill 源（`skills/schematic-reviewer/`），由 `build.py` 渲染出
WorkBuddy（Windows + Git Bash）与 Codex 两套可直接安装的产物。

## 构建

需要 Python 3.8+，只用标准库。

```bash
python build.py                     # 构建全部平台到 dist/
python build.py --platform codex    # 只构建指定平台
python build.py --check             # 只校验模板能否渲染，不写 dist/
python build.py --install workbuddy # 构建并直接装到 ~/.workbuddy/skills
python build.py --clean             # 删除 dist/
```

`--install` 覆盖同名 skill 前会先把原目录改名成 `<skill>.backup-<时间戳>` 留档。

产物：

```
dist/workbuddy/schematic-reviewer/    # 拷到 ~/.workbuddy/skills/ 即可
dist/codex/schematic-reviewer/        # 拷到 ~/.codex/skills/ 即可
dist/<平台>/BUILD.json                # 本次构建的平台、变量与文件清单
```

构建后建议校验一次产物：

```bash
python build.py --check             # 残留标记或未定义占位符会直接报错退出
```

### 为什么要有构建这一步

两套产物 90% 的内容是一样的，差异只有三处：

1. **工具映射**：WorkBuddy 用 Read / WebFetch / Bash，Codex 用 `pdf` skill 与 shell 抓取。
2. **跑脚本的方式**：WorkBuddy 用托管 Python 绝对路径，Codex 用相对路径 `python scripts/...`。
3. **frontmatter 与专属文件**：WorkBuddy 多 `agent_created` / `metadata.short-description`；
   Codex 多 `agents/openai.yaml`。

把这三处抽出来之后，脚本、测试、参考资料只留一份，不会再出现「改了一边忘了另一边」的漂移。
语法细节见 [../platforms/README.md](../platforms/README.md)。

## 安装

### WorkBuddy

```bash
python build.py --install workbuddy
```

或手动拷贝：

```bash
cp -r dist/workbuddy/schematic-reviewer ~/.workbuddy/skills/
```

装好后 skill 目录下的 `SKILL.md` 会带一段「WorkBuddy 环境适配」，其中定义了脚本目录与
托管 Python 解释器；本技能会据此用 `"$PY" "$SK/xxx.py"` 的形式调用脚本。

### Codex

```bash
python build.py --install codex
```

或手动拷贝：

```bash
cp -r dist/codex/schematic-reviewer ~/.codex/skills/
```

## 规范符合性

产物按 Agent Skills 规范组织（参考 anthropics/skills 的 skill-creator 与官方 best-practices）：

| 要求 | 本仓库的做法 |
|---|---|
| `SKILL.md` 必填 `name` + `description` | 都有；`name` 为小写连字符，`description` 单行、第三人称、含“做什么 + 何时触发” |
| `description` 不得含尖括号、≤1024 字符 | 不用 YAML 的 `>-` 折叠标量（那个 `>` 会被朴素校验器判成尖括号），写成语义等价的单行标量 |
| 目录只放 `SKILL.md` + `scripts/` + `references/`（+ 功能性 `tests/`） | 是；不放 `README.md` 之类附属文档，给人看的说明放在 `docs/` |
| `SKILL.md` 正文 ≤ 500 行 | 是（产物 247 行 / 268 行） |
| 渐进披露：细节放 `references/`，只被 `SKILL.md` 直接引用（引用深度 ≤ 1 层） | 是；`references/` 之间不互相链接 |
| 长参考文件（>100 行）带目录 | 是 |
| 把会失败的点单独收敛成 Gotchas 章节 | 是，见 `SKILL.md` 的「Gotchas（踩过的坑）」 |
| 确定的计算下沉到脚本，不让模型现推 | 是；载流计算、参数比对、解析全部走 `scripts/` |

`description` 不用 `>-` 是一个容易踩的点：WorkBuddy 自带的 `quick_validate.py` 会报
`Description cannot contain angle brackets`，即使内容里根本没有尖括号——它把 YAML 折叠标量的
`>` 当成了尖括号。写成单行标量两边都干净。
