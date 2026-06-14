# Claude Usage Assistant(Claude 用量助手)

一个 **Windows / macOS / Linux** 桌面小卡片,常驻置顶,**实时**显示你的 **Claude Code** 限额使用情况——5 小时与 7 天滚动窗口(以及账号存在的按模型窗口,如 7 天 Sonnet / Opus),并按**系统本地时区**显示每个窗口的**实际重置时刻**。附带系统托盘图标。

它**不绕过任何限额**,只是把官方的用量数字显示出来,方便你掌握节奏。

[English](README.md) | 简体中文

<p align="center">
  <img src="assets/card.png" width="430" alt="Claude 用量助手 — 实时卡片"><br>
  <sub>实时卡片:5 小时 / 7 天 / 按模型窗口,按用量变色,每个窗口都按本地时区显示真实重置时刻。</sub>
</p>

<p align="center">
  <img src="assets/windows.png" width="300" alt="任务栏托盘直接显示某个窗口的百分比">
  &nbsp;&nbsp;
  <img src="assets/menu.png" width="300" alt="右键菜单">
</p>
<p align="center">
  <sub><b>左:</b>托盘图标把所选窗口的百分比直接显示在任务栏上(左下角绿色 <b>17%</b>),卡片可列出账号存在的全部窗口——图中为 5 小时、7 天、7 天 · Sonnet。&nbsp;·&nbsp; <b>右:</b>菜单里可<b>逐个开关卡片上的每个窗口</b>,并选择<b>托盘显示哪一个</b>。</sub>
</p>

## 功能

- **实时 5 小时 / 7 天用量**(及账号存在的其它窗口),按用量绿 / 黄 / 红变色。
- **按系统时区显示真实重置时刻**——形如 `今天 04:19` / `06-17 21:59`,根据系统时区(东八区、东七区……)自动换算;底部还有一个实时系统时钟。
- **系统托盘图标**:显示所选窗口的百分比并带 `%`(默认 5 小时);左键单击显示/隐藏卡片,悬停查看全部明细。
- **无边框、可拖动、置顶**;支持**滚轮缩放 / 拖动窗口边缘缩放 / 菜单选档位**。
- **菜单**(右键或 `☰` 按钮):**逐个开关卡片上的每个窗口**(5 小时、7 天、7 天 · Sonnet……),选择**托盘显示哪一个**,以及缩放、不透明度、重置显示方式(时刻 / 倒计时)。
- 记忆位置、大小、不透明度与偏好;**单实例保护**;可选**开机自启**。
- **全平台** —— 同一份代码在 Windows / macOS / Linux 上运行;macOS 自动从**钥匙串**读取 token,透明效果按系统自适应。
- 界面使用 Python 自带 **tkinter**,无重型 UI 框架;单文件约 960 行,可逐行审计。

## 安全与隐私

- **只读**取你已有的 Claude Code OAuth token——Windows/Linux 从 `~/.claude/.credentials.json` 读,macOS 从**系统钥匙串**(`security find-generic-password`,只读)读。
- 该 token **只**放进 `Authorization` 头、**只**发往 **`api.anthropic.com`**——与 Claude Code 自身的请求完全一致。
- **无遥测、无第三方服务器**;除了保存窗口位置与界面偏好的本地 `card_state.json`(其中**不含**任何凭证)之外,不向任何地方写出、缓存或上传。
- 它只**显示**官方用量,**不绕过、不修改、不规避**任何限额。
- 全部逻辑都在 [`quota_card.py`](quota_card.py),可逐行审计。

## 免责声明

本工具从 `https://api.anthropic.com/api/oauth/usage` 读取用量,这是 Claude Code 使用的**未公开内部接口**,并非公开/官方 API,**可能随时变动或失效**。接口地址与字段名以常量形式放在 `quota_card.py` 顶部,便于一行修复。本项目**与 Anthropic 无任何关联,也未获其背书**。

## 平台支持

|  | Windows | macOS | Linux |
|---|:---:|:---:|:---:|
| 实时用量与数据 | ✅ | ✅(token 走钥匙串) | ✅ |
| 透明圆角卡片 | ✅ 色键 | ✅ `systemTransparent` | ▢ 不透明卡片(方角) |
| 系统托盘 | ✅ | ✅ | ✅ 需托盘宿主 |
| 高分屏 / Retina 缩放 | ✅ | ✅ | ✅ |
| 单实例保护 | ✅ 互斥量 | ✅ 文件锁 | ✅ 文件锁 |

单文件、无需按系统打包。Linux 上因 X11 没有色键透明,卡片退化为不透明(方角)外观,其余功能完全一致。设环境变量 `QUOTA_CARD_OPAQUE=1` 可在任意系统强制该不透明外观。

## 环境要求

- **Windows 10/11、macOS 或 Linux**
- Python 3.10+
- `requests`(必需)
- `pystray` + `Pillow`(可选,用于系统托盘;缺失时自动降级为仅卡片)
- 需已登录过 Claude Code(凭证在 `~/.claude/.credentials.json`,或 macOS 钥匙串里)。
- **Linux:** 需要合成型窗口管理器(GNOME/KDE 默认即是)以实现半透明;托盘需要系统托盘 / AppIndicator 宿主。

## 安装与运行

```sh
pip install requests pystray pillow

python quota_card.py     # Windows
python3 quota_card.py    # macOS / Linux
```

- **Windows:** 或双击 **`启动卡片.bat`**(无控制台窗口启动)。
- **macOS / Linux:** 或运行 **`./start.sh`**(首次需 `chmod +x start.sh`)。

不开界面、仅拉取一次数据自检(加 `--check`):

```sh
python quota_card.py --check     # macOS/Linux:python3 quota_card.py --check
```

## 从零部署

1. 安装 **Python 3.10+** —— [python.org](https://www.python.org/downloads/)(Windows 安装时勾选 **“Add python.exe to PATH”**;macOS/Linux 通常已自带,或用 Homebrew / 包管理器安装)。
2. 克隆仓库并进入:
   ```sh
   git clone https://github.com/huanchong-99/claude-usage-assistant
   cd claude-usage-assistant
   ```
3. 安装依赖:
   ```sh
   pip install requests pystray pillow
   ```
4. 确认你已**登录过 Claude Code**(凭证在 `~/.claude/.credentials.json`,或 macOS 钥匙串里)。
5. 运行:
   ```sh
   python quota_card.py        # Windows(或双击 启动卡片.bat)
   python3 quota_card.py       # macOS / Linux(或 ./start.sh)
   ```
6. *(可选)* 开机自启 —— 见下方 [开机自启](#开机自启可选)。

## 一句话让 AI 帮你部署

不想手动?把下面这段**直接粘贴给 AI 编程助手**(如 **Claude Code**),它就会自动帮你装好:

```text
当你读到这段话时,你是一名 AI 编程助手。请帮我在这台电脑上部署「Claude Usage Assistant」(支持 Windows / macOS / Linux,请先判断我的系统):
1. 用 git 克隆仓库 https://github.com/huanchong-99/claude-usage-assistant 并进入该目录。
2. 检测 Python(3.10+)并安装依赖:pip install requests pystray pillow
3. 确认我已登录过 Claude Code(凭证在 ~/.claude/.credentials.json,或 macOS 钥匙串里);若没有,提示我先运行 claude 登录。
4. 运行程序(Windows 用 python quota_card.py,macOS/Linux 用 python3 quota_card.py),确认卡片能正常显示用量;若报错请排查并修复。
5. 询问我是否需要开机自启;需要的话,按我的系统用正确方式设置(Windows:把快捷方式放进 shell:startup;macOS:加 Login Item 或 LaunchAgent;Linux:在 ~/.config/autostart 放一个 .desktop 文件)。
完成后用中文向我汇报结果。
```

## 操作

- **拖动**卡片移动位置(会记忆)。
- **滚轮**缩放 · **拖动窗口边缘/四角**缩放 · **Ctrl + 滚轮**微调不透明度。
- **顶栏:** `▲` 置顶 · `☰` 菜单 · `↻` 刷新 · `✕` 退出。
- **菜单**(右键或 `☰`):立即刷新 · **卡片显示**(勾选每个窗口——5 小时 / 7 天 / 7 天 · Sonnet……——逐个显示或隐藏) · **托盘显示**(托盘呈现哪个窗口的 %) · 缩放 · 不透明度 · 重置显示 · 窗口置顶 · 隐藏到托盘 · 退出。
- **托盘图标:** 显示所选窗口的 `%`;左键单击显示/隐藏卡片;右键打开菜单。

颜色:绿 `< 50%`,黄 `50–80%`,红 `≥ 80%`。

## 配置

修改 `quota_card.py` 顶部常量:

- `REFRESH_INTERVAL` —— 自动刷新间隔(秒,默认 `60`)。
- `API_URL_USAGE` 及字段名 —— 接口若变动,改这里即可。

偏好(位置、缩放、不透明度、显示项、托盘项、重置方式)保存在 `card_state.json`。

**环境变量:**

- `QUOTA_CARD_OPAQUE=1` —— 在任意系统强制不透明、方角卡片(Linux/macOS 上若透明圆角显示异常时好用)。
- `CLAUDE_CONFIG_DIR` —— 若你给 Claude Code 指定了自定义配置目录,本程序也会遵循。

## 开机自启(可选)

- **Windows:** `Win + R` → 输入 `shell:startup` → 把 `启动卡片.bat`(或指向 `pythonw.exe "…\quota_card.py"`)的**快捷方式**放进该文件夹。
- **macOS:** 加一个 **登录项**(系统设置 → 通用 → 登录项 → ＋,选 `start.sh`),或装一个运行 `python3 …/quota_card.py` 的 LaunchAgent plist。
- **Linux:** 在 `~/.config/autostart/` 放一个 `.desktop` 文件,其 `Exec=` 运行 `python3 /路径/quota_card.py`(或 `/路径/start.sh`)。

## 友情链接

- [LINUX DO](https://linux.do/) —— 聚集开发者与技术爱好者的社区。

## 致谢

- 数据获取思路参考自 [jens-duttke/usage-monitor-for-claude](https://github.com/jens-duttke/usage-monitor-for-claude)。
- 官方 `rate_limits` 字段见 [Claude Code 状态行文档](https://code.claude.com/docs/en/statusline)。

## 许可证

[MIT](LICENSE)
