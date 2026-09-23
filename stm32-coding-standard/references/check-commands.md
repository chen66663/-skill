# 可执行检查命令

本文件提供 `SKILL.md`「编码与注释」「控制流和可读性」「验证要求」等小节所需的具体命令。命令本身不是门禁：门禁数值见 [local-rules.md](local-rules.md)，判据和拆分要求见 `SKILL.md`。执行后把命令、工具版本和输出摘要写进审查报告。

使用约定：

- 路径按项目实际结构替换；示例使用 `Src`、`App`、`Inc`、`Drivers/CMSIS`。
- `rg`、`awk`、`iconv`、`pmccabe`、`scan-build` 属于 POSIX/Git-Bash 环境；Windows 下用 Git-Bash，或改用文中给出的 PowerShell 等价写法。
- 所有检查只对项目代码运行，排除 ST 库、CMSIS 和生成代码。
- 工具缺失或许可缺失时，在报告的「未验证事项」中列出，不要用其他证据替代。

## 1. 编码检查与转换

### 1.1 检测（三项检查：BOM、严格 GB2312 解码、UTF-8 特征字节）

存为 `tools/check_encoding.py` 后运行 `python tools/check_encoding.py .`。PowerShell 不支持 heredoc，不要把脚本直接贴在命令行里。

```python
import pathlib, sys, re

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
utf8_cjk = re.compile(rb'[\xe4-\xe9][\x80-\xbf]{2}')

for p in sorted(root.rglob('*')):
    if p.suffix.lower() not in ('.c', '.h') or not p.is_file():
        continue
    b = p.read_bytes()
    flags = []
    if b.startswith(b'\xef\xbb\xbf'):
        flags.append('有 UTF-8 BOM')
    if b'\xef\xbf\xbd' in b:
        flags.append('含 U+FFFD 替换字符')
    if utf8_cjk.search(b):
        flags.append('含 UTF-8 三字节中文序列')
    try:
        b.decode('gb2312')
    except UnicodeDecodeError as e:
        flags.append('非 GB2312（偏移 %d：%s）' % (e.start, e.reason))
    if flags:
        print('%-60s %s' % (p, '；'.join(flags)))
```

判读规则：

- 命中「含 UTF-8 三字节中文序列」或「有 UTF-8 BOM」：该文件是 UTF-8，按缺陷处理。
- 只命中「非 GB2312」：可能实际是 GBK 或其他编码，先人工确认，不要直接转换。
- 三项都不命中：视为符合 GB2312。
- 任一项命中都要先备份再转换；无法确认原编码时停止批量转换。

粗查是否还有 UTF-8 中文残留（Git-Bash）：

```bash
rg -l -P '[\xe4-\xe9][\x80-\xbf]{2}' --glob '*.{c,h}'
```

### 1.2 转换

Git-Bash / Linux，先备份再转换，转换后立刻重跑 1.1 的检测：

```bash
iconv -f UTF-8 -t GB2312 -o file.c.gb2312 file.c && mv file.c file.c.utf8.bak && mv file.c.gb2312 file.c
```

PowerShell（写 GB2312，等价于代码页 936）：

```powershell
$p = 'Src\module.c'
$t = [IO.File]::ReadAllText($p, [Text.Encoding]::UTF8)
[IO.File]::WriteAllText($p, $t, [Text.Encoding]::GetEncoding('GB2312'))
```

## 2. 注释率与圈复杂度

### 2.1 注释率（工程整体统计，不对单文件设配额）

Git-Bash 分两步统计（第二行是整行注释数，属保守下限口径）：

```bash
git ls-files '*.c' '*.h' | xargs wc -l | tail -1
git ls-files '*.c' '*.h' | xargs grep -c '^[[:space:]]*\(/\*\|\*\)' | awk -F: '{s+=$NF} END{print s}'
```

该口径不计行尾注释和 `*/` 收尾行，结果低于实际值。审查报告必须写明所用口径和命令，不同口径的数字不能直接比较。

### 2.2 圈复杂度、函数长度与嵌套

- `lizard`（跨平台，可算 CCN、函数长度和参数个数）：

  ```bash
  pip install lizard
  lizard -C 10 -L 200 -w .
  ```

  阈值参数以 `lizard --help` 为准；升级版本后重新确认参数含义。

- `pmccabe`（Git-Bash，只给 CCN）：

  ```bash
  pmccabe -v $(git ls-files '*.c') | sort -rn | head -20
  ```

- clang-tidy 的复杂度与函数体积检查可作补充，但不能替代 CCN 数值统计：

  ```bash
  clang-tidy -p build -checks='-*,readability-function-cognitive-complexity,readability-function-size' Src/*.c
  ```

- 报告中每个超标函数都要给出 CCN、嵌套深度和具体拆分方案；恰好等于 10 的标记为临界值并说明是否需要提前重构。

## 3. 不安全函数与危险模式扫描

```bash
rg -n --glob '*.{c,h}' '\b(gets|strcpy|strcat|sprintf|vsprintf|scanf|sscanf|alloca)\s*\('
rg -n --glob '*.{c,h}' '\b(malloc|calloc|realloc|free)\s*\('
rg -n --glob '*.{c,h}' '\bgoto\b'
rg -n --glob '*.{c,h}' '//'
rg -n -P --glob '*.{c,h}' '(?<![=!<>+\-*/%&|^])=(?!=)'
rg -n --glob '*.{c,h}' '\b(__packed|__attribute__\s*\(\s*\(\s*(packed|aligned|section))'
```

说明：`//` 会命中字符串和 URL，属误报，需人工确认；赋值粗查只用于定位可疑位置，必须逐条复核，不能直接当缺陷计数。

## 4. 静态分析

### 4.1 前置条件

- CMake 工程生成编译数据库：

  ```bash
  cmake -S . -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
  ```

- 非 CMake 工程（CubeIDE/Keil/IAR/Makefile）用 `bear -- make` 或 `compiledb` 生成，或手工补一份最小 `compile_commands.json`。
- 交叉编译工程必须让分析器知道目标平台，否则头文件和内建定义不匹配会造成大面积误报：

  ```bash
  clang-tidy -p build --query-driver=$(which arm-none-eabi-gcc) Src/*.c
  clang-tidy -p build --extra-arg=--target=arm-none-eabi --extra-arg=-mcpu=cortex-m4 Src/*.c
  ```

  第二行用于当前 clang-tidy 版本不支持 `--query-driver` 的情况。
- MISRA 规则文本属付费标准内容：`cppcheck --addon=misra.py` 必须同时提供合法的规则文件，缺失时输出以规则缺失为主，不能作为合规证明。

### 4.2 cppcheck

```bash
cppcheck --enable=warning,style,performance,portability \
  --std=c11 --language=c \
  --suppress=missingIncludeSystem --inline-suppr \
  -D STM32F407xx \
  -I Inc -I Drivers/CMSIS/Include -I Drivers/STM32F4xx_HAL_Driver/Inc \
  --xml --xml-version=2 --output-file=cppcheck.xml \
  Src App
```

注意：`--enable=all` 会引入 `information` 与 `missingInclude` 噪声，不建议作为默认口径；`-D` 的器件宏必须与工程实际一致，否则结论无效。

MISRA 检查（取得合法规则文本后）：

```bash
cppcheck --enable=style --addon=misra.py Src App
```

### 4.3 clang-tidy 与 Clang Static Analyzer

```bash
clang-tidy -p build --query-driver=$(which arm-none-eabi-gcc) Src/*.c
scan-build --use-analyzer=clang -o report cmake --build build
```

报告按「本次新增」和「历史遗留」分开归档；禁止用大面积抑制把报告刷绿。

## 5. 构建基线与产物

改动前采集一次基线，改动后用完全相同的命令重采。

| 构建系统 | 命令 | 产物与度量 |
| --- | --- | --- |
| Makefile | `make V=1 2>&1 \| tee build.log` | `arm-none-eabi-size build/app.elf`、`.map` |
| CMake | `cmake --build build 2>&1 \| tee build.log` | `arm-none-eabi-size build/app.elf`、`arm-none-eabi-objdump -h` |
| CubeIDE | `stm32cubeide -nosplash -application org.eclipse.cdt.managedbuilder.core.headlessbuild -data . -build <project>/<config>`，或 `make -C Debug all` | `Debug/*.map`、`.elf` |
| Keil MDK | `UV4 -b project.uvprojx -j0 -o build.log` | `Objects/*.map` 的 Code/RO/RW/ZI |
| IAR | `iarbuild project.ewp -build Debug -log warnings` | `Debug/List/*.map` 的 read-only code / read-write data |

必须写进报告的采集内容：

- errors 与 warnings 数量（Debug/Release 两套设置都要）；
- 代码段、只读数据段、RAM 用量以及改动前后差异；
- 栈余量证据：`_Min_Stack_Size`、map 中的栈用量、ISR 最大嵌套深度，以及水位检测或 MPU 保护区；
- 产物路径（`.elf`/`.hex`/`.axf`）、map 文件路径和工具链版本。

编码与行尾核验（确认非目标字节未被改动）：

```powershell
$p = 'Src\module.c'
$b = [IO.File]::ReadAllBytes($p)
$t = [IO.File]::ReadAllText($p)
$cr = ($t.ToCharArray() | Where-Object { $_ -eq [char]13 }).Count
$lf = ($t.ToCharArray() | Where-Object { $_ -eq [char]10 }).Count
Write-Output ($p + ' bytes=' + $b.Length + ' CRLF=' + $cr + ' bareLF=' + ($lf - $cr))
```

```bash
git diff --numstat
```

## 6. 报告中怎么用

- 每条发现附上产生它的命令、工具版本和输出摘要；只写「已检查」不算证据。
- 命令无法执行（工具缺失、许可缺失、编译数据库不完整）时，在报告「未验证事项」中列明，不要用其他证据替代。
- 板级测试（示波器、逻辑分析仪、CAN 压力测试、HIL）不在本文件覆盖范围，必须单列。
