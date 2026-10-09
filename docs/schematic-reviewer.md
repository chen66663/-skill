# schematic-reviewer（原理图检查专家）

原理图检查与审核 skill。读数据手册做引脚级分析、查外围电路、算载流线宽、核验立创元器件参数与库存。
本仓库只维护一份源（`skills/schematic-reviewer/`），由 `build.py` 渲染出 WorkBuddy 与 Codex 两套产物，
两者的差异集中在下文的对照表里。

> 这份文档是给人看的，不随 skill 安装。skill 目录里只有 `SKILL.md`、`scripts/`、`references/`、`tests/`
> —— 按 Agent Skills 官方约定，skill 包里不放 README 之类的附属文档。

## 功能

- 读数据手册做逐引脚分析，提取设计约束（电源、上下拉、电平、驱动能力）
- 一条命令预检嘉立创 EDA/BOM 导出：解析、按型号去重、并发查询、缓存、问题筛选
- 解析 BOM 卡片和带表头的 CSV/TSV 元件表，生成统一器件清单
- 解析带网络连接的 `.tel` 网表（`位号.引脚号` 即连接证据）
- 对照外部权威 checklist 检查外围电路：去耦、复位与配置、时钟、接口电平、模拟前端、功率路径、ESD
- 识别大电流路径，按 IPC-2221 计算走线宽度并给出加宽建议
- 通过立创/JLC 接口核实元器件规格与现货库存，缺货给替代型号
- 直接输出问题清单，不生成报告 / HTML / 图片

## 目录结构（安装后的 skill）

```
schematic-reviewer/
|-- SKILL.md                        主流程、输出原则、Gotchas 与约束
|-- agents/openai.yaml              UI 元数据（仅 Codex 产物有）
|-- scripts/
|   |-- review_export.py             导出预检：解析、去重、并发查询与问题筛选
|   |-- parse_schematic_export.py   BOM 卡片与 CSV/TSV 元件表解析
|   |-- parse_tel_netlist.py        .tel 网表解析（$PACKAGES/$NETS）
|   |-- lcsc_lookup.py              立创/JLC 元器件查询
|   `-- trace_width.py              IPC-2221 载流计算
|-- tests/                          4 个回归测试，共 23 项
`-- references/
    |-- eda-export-format.md        导出格式、命令与证据边界
    |-- external-resources.md       权威 checklist 索引与手册获取
    |-- lcsc-guide.md               接口用法、字段、避坑
    |-- peripheral-rules.md         外围电路核心规则速查
    `-- trace-current-table.md      载流速查表（由脚本生成）
```

## 运行脚本

两套产物里命令的写法不同，语义完全一样：

| | WorkBuddy | Codex |
|---|---|---|
| 解释器 | 托管 Python 绝对路径，先定义 `$PY` | `python` |
| 脚本位置 | `$SK` 指向 skill 的 `scripts/` 目录 | 相对路径 `scripts/` |
| 预检 | `"$PY" "$SK/review_export.py" export.txt --jobs 6` | `python scripts/review_export.py export.txt --jobs 6` |

WorkBuddy 下先在 Bash 里定义一次（脚本只依赖标准库，已用托管 Python 3.13 验证）：

```bash
SK="$HOME/.workbuddy/skills/schematic-reviewer/scripts"
PY=$(ls -1 "$HOME"/.workbuddy/binaries/python/versions/*/python.exe 2>/dev/null | sort -V | tail -n1)
```

不要用裸 `python` / `py`，PATH 里可能命中别的解释器。Codex 下直接 `python scripts/xxx.py`。

常用命令（把前缀按上表替换即可）：

```bash
# 一条命令预检导出：解析、去重、批量核验，只输出问题
<前缀>review_export.py export.txt --jobs 6
<前缀>review_export.py export.txt --verbose
<前缀>review_export.py export.txt --json

# 解析嘉立创 EDA/BOM 导出
<前缀>parse_schematic_export.py export.txt
<前缀>parse_schematic_export.py export.txt --format json
<前缀>parse_schematic_export.py export.txt --format lcsc

# 解析带网络连接的 .tel 网表
<前缀>parse_tel_netlist.py netlist.tel
<前缀>parse_tel_netlist.py netlist.tel --pins U1
<前缀>parse_tel_netlist.py netlist.tel --net NRST

# 元器件核实
<前缀>lcsc_lookup.py get C8734
<前缀>lcsc_lookup.py search "0603 100nF 50V X7R" --in-stock
<前缀>lcsc_lookup.py bom mpn_list.txt --jobs 6

# 载流计算
<前缀>trace_width.py width --current 3 --copper 1 --layer outer --dt 10
<前缀>trace_width.py current --width 50 --copper 1 --layer outer --dt 10
<前缀>trace_width.py table
```

`.tel` 解析不依赖固定排列顺序：会扫描并识别 `$PACKAGES`/`$COMPONENTS`、`$NETS`/`$NETWORKS` 等别名，支持字母数字混合引脚号（如 `U1.A1`）。除解析告警外，输出还包含 `connectivity_findings`，用于列出重复网络段、同器件多引脚连写等需要结合数据手册确认的拓扑事项。

解析结果还会保留器件字段状态：

- `value_status=literal`：Value 是实际值，可用于参数核对。
- `value_status=placeholder`：Value 是 `{Value}`，只能说明原理图库没有展开 Value。
- `datasheet_status=url`：型号记录中包含可追踪 URL。
- `datasheet_status=placeholder`：存在 `{Datasheet}`，但需要继续从型号、厂商或 LCSC 信息补齐手册。

这些状态会出现在 JSON 的 `packages` 记录中，摘要中也会给出占位字段计数；占位符本身不作为解析失败。

`parse_schematic_export.py` 会自动识别：

- 多行 BOM 卡片：`封装 ! 型号+属性 ! 参数 ,`，下一行以 `;` 给位号。
- 同行 BOM 卡片：`封装 ! 型号+属性 ! 参数 ; C1 C2`。
- 带表头的 CSV/TSV 元件表，例如 `Comment,Designator,Footprint,LCSC Part #` 或 `Value,References,Package,MPN`。
- `C1-C3` 这类位号范围会展开为 `C1 C2 C3`。
- 含 `$PACKAGES` 与 `$NETS` 的 `.tel` 会被明确分流到 `parse_tel_netlist.py`，不会再被伪装成器件清单解析。

## 工具映射

| 任务 | WorkBuddy | Codex |
|---|---|---|
| 读原理图图片 / PDF | Read 工具（原生多模态与 PDF 解析） | 直接查看图片文件；PDF 用 `pdf` skill |
| 抓外部 checklist、在线手册页 | WebFetch（自动转 markdown） | shell 里 `curl` / `Invoke-WebRequest` |
| 下载手册 PDF | Bash `curl -L -o <file> "<URL>"`，校验文件头 `%PDF-` | 同上（无浏览器自动化工具） |
| 立创元器件数据 | 只能用 `lcsc_lookup.py` 接口 | 同上，抓网页拿不到数据 |
| 跑脚本 | Bash（Git Bash，正斜杠路径） | shell，相对路径 `scripts/` |

## 验证

23 项回归测试，在仓库里直接跑：

```bash
cd skills/schematic-reviewer
python tests/test_review_export.py
python tests/test_lcsc_lookup.py
python tests/test_parse_schematic_export.py
python tests/test_parse_tel_netlist.py
```

WorkBuddy 下已装的 skill 用 `"$PY" tests/test_xxx.py`，并先 `cd "$HOME/.workbuddy/skills/schematic-reviewer"`。

本机已验证：23 项全部通过；`lcsc_lookup.py get C8734` 实返回 STM32F103C8T6 库存 148295。

## 效率设计

- `review_export.py` 默认按型号去重，再以 6 路并发查询立创/JLC，保留位号汇总与原始顺序。
- 查询结果默认缓存 24 小时；重复审查同一导出不会再次请求接口。
- 默认只显示解析告警、未精确匹配、无现货、封装冲突、参数冲突和关键参数无法核实项。
- 参数比较支持常见单位换算（如 `0.1uF = 100nF`）与 `NP0 = C0G` 等常见等价写法。

## 环境要求

- Python 3.8+，脚本只依赖标准库
- 可访问 `jlcpcb.com`（元器件接口）与厂商数据手册站点
- WorkBuddy 下用托管 Python 绝对路径，不要用裸 `python`

## 已知限制

- 无浏览器自动化：立创商城网页是 JS 单页应用，抓 HTML 拿不到商品数据，必须走接口。
- 嘉立创 EDA/BOM 导出通常只有器件参数，没有网络连接；不能据此判断具体引脚接线。带 `$NETS` 的 `.tel`
  可以核对 `位号.引脚号`，但仍没有坐标和封装引脚名，无法判断去耦是否靠近引脚或走线宽度。
- 元器件接口为第三方公开接口，无鉴权但可能变更；失效时脚本会明确报错，需重新探查接口。
- 立创手册链接是在线阅读页而非 PDF 直链，数据手册优先从厂商官网取。
- 导出预检只覆盖型号、库存、封装和可获得的器件参数，不代表已完成原理图网络级检查。
