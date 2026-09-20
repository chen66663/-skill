---
name: schematic-reviewer
description: >-
  原理图检查与审核专家：读芯片数据手册做逐引脚分析，识别去耦、上拉、匹配等外围元件缺失或参数错误，
  标注大电流路径并给出 PCB 走线加宽建议，通过立创/JLC 接口核实元器件规格（耐压、额定电流、封装）
  与现货库存。适用于原理图审核、电路设计自检、元器件选型验证、BOM 参数核对、PCB 布线前载流检查。
  触发词：检查原理图、审核电路、原理图有没有问题、元器件选型、立创选型、走线加宽、载流、外围电路、
  引脚功能、数据手册、BOM 核对。不适用于 PCB 布局的 DRC/阻抗检查、电路仿真、固件代码审查，
  也不检查铜柱、螺柱、螺钉、螺母、垫片等机械结构件。
argument-hint: "[full|pins|peripheral|trace|bom] [原理图文件或电路描述]"
---

# 原理图检查专家

## 输出原则

- **只列有问题的部分**，直接说哪里有问题、怎么改。不生成图片或 HTML，不写概述/总结/检查依据等报告套话。
- **每条结论必须有依据**：数据手册页码或章节名、外部 checklist 条目、接口返回的实际参数、可复现的载流计算。
- **元器件关键参数必须查接口核实**——耐压、额定电流、功率等不凭记忆填写。
- **选型必须确认现货库存大于 0**，缺货件要标注并给出替代型号。
- **不检查机械结构件**：铜柱、螺柱、螺钉、螺母、垫片等机械件不纳入原理图审查、BOM 电气参数核对或库存核对，除非用户明确要求核对机械装配。
- 没有问题的方面不写；确实没问题就直接说"没发现明显问题"，不要凑内容。

## 本环境可用工具

| 任务 | 用什么 |
|---|---|
| 读原理图图片（PNG/JPG） | 直接查看图片文件，逐模块识别器件 |
| 读原理图 PDF | `pdf` skill（转图片识别，或提取文字与网表） |
| 读数据手册 PDF | `pdf` skill；下载后先确认文件头是 `%PDF-` |
| 元器件规格与库存 | `scripts/lcsc_lookup.py`（见下） |
| 载流计算 | `scripts/trace_width.py`（见下） |
| 抓数据手册 / checklist | shell 里用 `curl` 或 `Invoke-WebRequest` 抓取 |

> 本环境**没有浏览器自动化工具**，也没有 PDF 之外的专用阅读技能。立创商城网页是 JS 单页应用，
> 直接抓 HTML 拿不到商品数据，元器件信息一律走接口。

## 元器件核实：立创/JLC 接口

```bash
python scripts/lcsc_lookup.py get C8734
python scripts/lcsc_lookup.py search "0603 100nF 50V X7R" --in-stock
python scripts/lcsc_lookup.py search "SOT-23 N-MOS 30V" --limit 5
python scripts/lcsc_lookup.py bom mpn_list.txt
```

脚本返回：立创编号、品牌、型号、封装、现货库存、阶梯价、`attributes` 规格参数、手册链接、商品页。

- 关键词既可以是型号，也可以是参数组合（`0603 100nF 50V X7R`），后者用于选型和找替代料。
- 与立创商城同源，数据即立创商品库，满足"以立创为准"的要求。
- 接口、字段与注意事项详见 [references/lcsc-guide.md](references/lcsc-guide.md)。
  其中记录了必须避开的坑：不要传 `componentLibraryType: "base"`，按 C 编号搜索必须精确比对 `componentCode`。
- 脚本不可用时，直接 POST `https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList`，body 为 `{"currentPage":1,"pageSize":20,"keyword":"<关键词>"}`。

## 数据手册获取

1. 优先抓**厂商官网 PDF**（如 `https://www.st.com/resource/en/datasheet/<型号>.pdf`），一般可直接下载。
2. 接口返回的 `dataManualUrl` 可作线索，但它是 LCSC 在线阅读页而非 PDF 直链。
3. 下载后校验：文件头应为 `%PDF-`；若是 `<!doctype html>` 说明被拦，换来源。
4. 用 `pdf` skill 读取，**必须读到**：Pin Configuration、Recommended Operating Conditions、
   Electrical Characteristics、Absolute Maximum Ratings、Application Information/Typical Application、
   Layout Guidelines。
5. 手册很长时按关键词定位（"pin description"、"decoupling"、"layout"、"application circuit"），不要逐页通读。

## 工作流程

按顺序执行，每一步的产出作为下一步的输入。用户只要求某一项检查时（如仅 `trace` 或仅 `bom`），只做对应步骤。

### 第 1 步：输入解析与器件清单

输入可能是原理图图片、原理图 PDF、网表/文本描述，或口头描述的电路。

- 输出器件清单：`位号 | 型号 | 功能模块 | 关键引脚连接`
- 原理图模糊或型号无法辨认时，先列出可识别部分，明确告知用户哪些需要补充，**不要猜型号**。
- 用户只给了电路描述而没给图时，先问清输入形式，并索要关键芯片型号，不要凭空假设电路。

### 第 2 步：数据手册与引脚级分析

对每个 IC：

1. 按上面的方法拿到数据手册。
2. 逐个引脚记录约束：
   - 电源引脚：工作电压范围、是否需独立去耦、最大功耗/电流
   - 关键信号引脚：输入/输出/双向、是否需上拉或下拉、电平标准、是否开漏、驱动能力(mA)

产出：每个 IC 的引脚分析摘要，重点标注设计约束。

### 第 3 步：外围电路检查

1. 先抓外部 checklist 的相关章节，把它当作检查骨架（见 [references/external-resources.md](references/external-resources.md)）。
2. 结合数据手册的典型应用电路，逐项核对原理图。
3. 核心规则速查见 [references/peripheral-rules.md](references/peripheral-rules.md)，仅作补充，详细规则以外部 checklist 为准。

检查维度（按优先级）：

- **电源去耦**：每个 VDD 引脚旁是否有 0.1µF 去耦电容、是否靠近引脚；大容量储能电容；模拟/数字电源分离；陶瓷电容直流偏压降额
- **复位与配置引脚**：RESET 是否有上拉与滤波电容；strapping/配置引脚是否正确上下拉；是否有悬空输入引脚
- **时钟电路**：晶振负载电容是否匹配（CL = (C1×C2)/(C1+C2) + Cs，常见错误是 C1/C2 直接取 CL 值）
- **接口与电平匹配**：I2C 上拉及阻值是否匹配总线速度；UART TX/RX、SPI MOSI/MISO 是否交叉；跨电压域是否有电平转换；CAN 两端是否有 120Ω 终端电阻
- **模拟前端**：ADC 输入是否有抗混叠滤波；运放反馈极性；基准去耦；模拟/数字地单点连接
- **功率路径**：输入是否有反接保护、TVS、保险丝；LDO/DCDC 输入输出电容与反馈电阻；DCDC 电感饱和电流；感性负载续流二极管
- **ESD 与保护**：对外连接器是否有 ESD/TVS；TVS 钳位电压是否低于后级绝对最大额定值；高速信号 ESD 器件电容是否足够低

产出：问题清单，每条包含位号/引脚、问题描述、依据、修改建议、严重程度。

### 第 4 步：载流路径分析与走线加宽

1. **识别大电流节点**：电源主输入、电机驱动、LED 驱动、DCDC 开关节点(SW)、功率地(PGND)、USB 5V、充电电路。
2. **估算电流**：从数据手册取 IC 最大电流或负载额定电流；DCDC 输入电流 ≈ 输出电流 × (Vout/Vin) / 效率；电机启动电流按额定 3~5 倍。
3. **算线宽**：用 `python scripts/trace_width.py width --current <A> --copper 1 --layer outer --dt 10`，
   默认 1oz 铜厚、外层、温升 ≤10℃，建议留 1.5~2 倍裕量。数据表见 [references/trace-current-table.md](references/trace-current-table.md)。
4. **地平面**：模拟地/功率地单点连接；大电流回路面积尽量小。

产出：`路径 | 估算电流 | 建议最小线宽 | 备注`

### 第 5 步：元器件选型核实

对每个关键元器件核实规格与库存，必须核实的参数见 [references/lcsc-guide.md](references/lcsc-guide.md) 第三节。

- 用 `scripts/lcsc_lookup.py` 查询，或整份 BOM 用 `bom` 子命令批量核对。
- 库存为 0 的器件必须标注，并给出至少 1 个有现货的替代型号。
- 参数以接口返回为准；接口参数与数据手册冲突时以数据手册为准，并指出冲突。

产出：`位号 | 型号 | 设计要求 | 核实参数 | 是否满足 | 库存状态 | 替代型号`

### 第 6 步：直接输出问题

按严重程度分组，逐条列出，简洁直接：

```
🔴 严重问题（必须改，否则电路不工作或损坏器件）：
1. [位号/位置] [问题] → [怎么改]（依据：手册第 X 页 / checklist 条目）

🟡 警告（建议改，影响稳定性、EMC 或寿命）：
1. ...

🔵 建议（可选优化）：
1. ...

走线加宽：
- [路径] 电流约 X A，建议线宽 ≥ X mm（1oz 外层，温升 ≤10℃）

元器件问题（立创核实）：
- [位号] [型号] 耐压/电流不足或缺货 → 建议用 [替代型号]（有现货）
```

严重程度判定：

- 🔴 严重：电路不工作、损坏器件、安全隐患（去耦缺失、耐压不足、电源短路、电平不匹配、ESD 缺失）
- 🟡 警告：影响稳定性、EMC 或寿命（去耦距离远、上拉阻值偏大、走线裕量不足）
- 🔵 建议：不影响基本功能的优化项

## 关键约束

1. 禁止凭记忆填写元器件耐压、电流、功率等参数，必须查接口核实。
2. 禁止生成图片、HTML 或完整 MD 报告；直接列问题，不写概述/总结/检查依据等套话。
3. 数据手册引用必须标注页码或章节名。
4. 检查规则优先引用外部权威 checklist，不要只依赖本地 references。
5. 立创查询优先用脚本或接口，网页抓取拿不到数据。
6. 用户未提供原理图文件时，先询问输入形式，不要凭空假设电路。
7. 载流计算默认 1oz 铜厚；用户指定其它铜厚时按比例换算并注明假设。
8. 不将铜柱、螺柱、螺钉、螺母、垫片等机械结构件作为原理图电气问题、BOM 缺货问题或替代选型问题报告。
