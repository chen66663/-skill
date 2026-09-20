# 立创/JLC 元器件核实用法

> **数据源**：JLC SMT 元器件库接口。它与立创商城共用同一商品库，C 编号一致，无需鉴权即可匿名调用。
> **重要**：旧资料里的 `lcsc.com/api/global/additional/search`、`lcsc.com/api/products/search`、
> `wmsc.lcsc.com`、`so.szlcsc.com` 接口现在已经失效（返回 SPA 空壳 HTML 或 403），不要再用。

## 一、用脚本查询（首选）

```bash
python scripts/lcsc_lookup.py get C8734
python scripts/lcsc_lookup.py search "STM32F103C8T6" --limit 5
python scripts/lcsc_lookup.py search "0603 100nF 50V X7R" --in-stock
python scripts/lcsc_lookup.py bom mpn_list.txt
```

- `get <C编号>`：按立创编号精确查询，用于已知编号的复核。
- `search <关键词>`：关键词可以是型号，也可以是参数组合（`0603 100nF 50V X7R`、`SOT-23 N-MOS 30V`）。
- `bom <文件>`：批量核对，每行一个型号，`#` 开头为注释；无现货或查不到的会单独列出来。
- 加 `--json` 输出原始结构，`--brief` 只显示库存与价格。

## 二、直接调用接口（脚本不适用时）

```
POST https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList
Content-Type: application/json

{"currentPage": 1, "pageSize": 20, "keyword": "<型号或参数关键词>"}
```

返回 `data.componentPageInfo.list[]`，关键字段：

| 字段 | 含义 |
|---|---|
| `componentCode` | 立创 C 编号 |
| `componentModelEn` / `componentBrandEn` | 型号 / 品牌 |
| `componentSpecificationEn` | 封装 |
| `stockCount` | 现货库存 |
| `componentPrices` | 阶梯价（`startNumber` / `endNumber` / `productPrice`） |
| `attributes` | 规格参数（耐压、额定电流、容值、RDS(on) 等） |
| `describe` | 参数摘要 |
| `dataManualUrl` | 手册链接（LCSC 阅读页，不是 PDF 直链） |
| `lcscGoodsUrl` | 立创商品页 |
| `componentLibraryType` | `base` 基础库 / `expand` 扩展库 |
| `preferredComponentFlag` / `isBuyComponent` | 优选料 / 可购买 |

注意事项：

- **不要传 `componentLibraryType: "base"`**。它会把常见的扩展库型号过滤成 0 条结果（如 STM32F103C8T6 在基础库里查不到）。
- 按 C 编号搜索是模糊匹配，必须再按 `componentCode` 精确比对，不能直接取第一条。
- 接口返回 UTF-8 JSON；用 shell 工具时注意解码，避免中文参数（℃、Ω）变成乱码。

## 三、各类器件必须核实的参数

| 器件类型 | 必须核实参数 |
|---|---|
| 电容 | 耐压（≥工作电压×1.5~2）、容值、材质(X7R/X5R/C0G)、封装、ESR |
| 电阻 | 阻值、精度、功率额定值（≥实际功耗×2）、封装 |
| 电感 | 电感量、饱和电流（≥峰值电流×1.2）、DCR、封装 |
| 二极管 | 反向耐压 VRRM、正向电流 IF、正向压降 VF、封装 |
| MOS 管 | VDS 耐压、VGS 阈值、连续漏极电流 ID、RDS(on)、封装 |
| LDO | 输入电压范围、输出电压/电流、压差、静态电流、封装 |
| DCDC | 输入电压范围、输出电流、开关频率、效率、封装 |
| TVS | 反向工作电压 VRWM（≥工作电压）、钳位电压 VC（≤后级耐压）、峰值功率 |
| 晶振 | 频率、负载电容 CL、精度(PPM)、封装；区分无源晶振与有源晶振 |

## 四、库存与价格判断

- **现货**：`stockCount` > 0，可直接采购。
- **无现货**：`stockCount` 为 0，必须标注并给出替代型号，不要默认用户能等到货。
- **阶梯价**：`componentPrices` 是采购单价参考，量大时单价更低。
- **基础库 vs 扩展库**：基础库料（`base`）在 JLC 贴片时通常免上料费，优先推荐；扩展库（`expand`）有上料费但可选范围大。

## 五、替代型号

1. 用参数关键词重搜（如 `SOT-23 3.3V LDO 500mA`）。
2. 逐个比对关键参数，确保不低于原设计要求。
3. 确认替代型号 `stockCount` > 0。
4. 至少给出 1 个替代方案。
