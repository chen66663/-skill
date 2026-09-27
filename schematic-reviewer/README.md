# schematic-reviewer（原理图检查专家）

Codex skill：原理图检查与审核。读数据手册做引脚级分析、查外围电路、算载流线宽、核验立创元器件参数与库存。

## 功能

- 读数据手册做逐引脚分析，提取设计约束（电源、上下拉、电平、驱动能力）
- 一条命令预检嘉立创 EDA/BOM 导出：解析、按型号去重、并发查询、缓存、问题筛选
- 解析 BOM 卡片和带表头的 CSV/TSV 元件表，生成统一器件清单
- 对照外部权威 checklist 检查外围电路：去耦、复位与配置、时钟、接口电平、模拟前端、功率路径、ESD
- 识别大电流路径，按 IPC-2221 计算走线宽度并给出加宽建议
- 通过立创/JLC 接口核实元器件规格与现货库存，缺货给替代型号
- 直接输出问题清单，不生成报告/HTML/图片

## 目录结构

```
schematic-reviewer/
|-- SKILL.md                        主流程与约束
|-- agents/openai.yaml              UI 元数据（中文显示名）
|-- scripts/
|   |-- review_export.py             导出预检：解析、去重、并发查询与问题筛选
|   |-- parse_schematic_export.py   BOM 卡片与 CSV/TSV 元件表解析
|   |-- parse_tel_netlist.py        .tel 网表解析（$PACKAGES/$NETS）
|   |-- lcsc_lookup.py              立创/JLC 元器件查询
|   `-- trace_width.py              IPC-2221 载流计算
|-- tests/
|   |-- test_review_export.py       预检与参数判定回归测试
|   |-- test_lcsc_lookup.py         缓存、去重与并发查询回归测试
|   |-- test_parse_schematic_export.py  BOM 卡片与表格解析回归测试
|   `-- test_parse_tel_netlist.py       .tel 网表与引脚连接回归测试
`-- references/
    |-- eda-export-format.md        导出格式、命令与证据边界
    |-- external-resources.md       权威 checklist 索引与手册获取
    |-- lcsc-guide.md               接口用法、字段、避坑
    |-- peripheral-rules.md         外围电路核心规则速查
    `-- trace-current-table.md      载流速查表（由脚本生成）
```

## 脚本

```bash
# 一条命令预检导出：解析、去重、批量核验，只输出问题
python scripts/review_export.py export.txt --jobs 6
python scripts/review_export.py export.txt --verbose
python scripts/review_export.py export.txt --json

# 解析嘉立创 EDA/BOM 导出
python scripts/parse_schematic_export.py export.txt
python scripts/parse_schematic_export.py export.txt --format json
python scripts/parse_schematic_export.py export.txt --format lcsc

# 解析带网络连接的 .tel 网表
python scripts/parse_tel_netlist.py netlist.tel
python scripts/parse_tel_netlist.py netlist.tel --pins U1
python scripts/parse_tel_netlist.py netlist.tel --net NRST
`.tel` 解析不依赖固定排列顺序：会扫描并识别 `$PACKAGES`/`$COMPONENTS`、`$NETS`/`$NETWORKS` 等别名，支持字母数字混合引脚号（如 `U1.A1`）。除解析告警外，输出还包含 `connectivity_findings`，用于列出重复网络段、同器件多引脚连写等需要结合数据手册确认的拓扑事项。

# 元器件核实
python scripts/lcsc_lookup.py get C8734
python scripts/lcsc_lookup.py search "0603 100nF 50V X7R" --in-stock
python scripts/lcsc_lookup.py bom mpn_list.txt --jobs 6

# 载流计算
python scripts/trace_width.py width --current 3 --copper 1 --layer outer --dt 10
python scripts/trace_width.py current --width 50 --copper 1 --layer outer --dt 10
python scripts/trace_width.py table
```

`parse_schematic_export.py` 会自动识别：

- 多行 BOM 卡片：`封装 ! 型号+属性 ! 参数 ,`，下一行以 `;` 给位号。
- 同行 BOM 卡片：`封装 ! 型号+属性 ! 参数 ; C1 C2`。
- 带表头的 CSV/TSV 元件表，例如
  `Comment,Designator,Footprint,LCSC Part #` 或
  `Value,References,Package,MPN`。
- `C1-C3` 这类位号范围会展开为 `C1 C2 C3`。
- 含 `$PACKAGES` 与 `$NETS` 的 `.tel` 会被明确分流到
  `parse_tel_netlist.py`，不会再被伪装成器件清单解析。

## 验证

```bash
python tests/test_parse_schematic_export.py
python tests/test_parse_tel_netlist.py
python tests/test_lcsc_lookup.py
python tests/test_review_export.py
```

## 效率设计

- `review_export.py` 默认按型号去重，再以 6 路并发查询立创/JLC，保留位号汇总与原始顺序。
- 查询结果默认缓存 24 小时；重复审查同一导出不会再次请求接口。
- 默认只显示解析告警、未精确匹配、无现货、封装冲突、参数冲突和关键参数无法核实项。
- 参数比较支持常见单位换算（如 `0.1uF = 100nF`）与 `NP0 = C0G` 等常见等价写法。

## 环境要求

- Python 3.8+，只依赖标准库
- 可访问 `jlcpcb.com`（元器件接口）与厂商数据手册站点

## 已知限制

- 无浏览器自动化：立创商城网页是 JS 单页应用，抓 HTML 拿不到商品数据，必须走接口。
- 嘉立创 EDA/BOM 导出通常只有器件参数，没有网络连接；不能据此判断具体引脚接线。带 `$NETS` 的 `.tel` 可以核对 `位号.引脚号`，但仍没有坐标和封装引脚名。
- 元器件接口为第三方公开接口，无鉴权但可能变更；失效时脚本会明确报错，需重新探查接口。
- 立创手册链接是在线阅读页而非 PDF 直链，数据手册优先从厂商官网取。
- 导出预检只覆盖型号、库存、封装和可获得的器件参数，不代表已完成原理图网络级检查。
