# AI Usage Assistant(Claude / Codex / Gemini 用量助手)

一个 **Windows / macOS / Linux** 桌面小卡片,常驻置顶,**实时**显示你的 **Claude Code**、**OpenAI Codex** 与 **Google Gemini** 限额使用情况——5 小时与 7 天 / 每周滚动窗口(以及账号存在的按模型窗口,如 Claude 的 7 天 Sonnet / Opus / Fable),并按**系统本地时区**显示每个窗口的**实际重置时刻**。三个数据源**可任意组合**。附带系统托盘图标。

它**不绕过任何限额**,只是把官方的用量数字显示出来,方便你掌握节奏。

> **不用终端也能刷新。** 只用 **Claude 桌面版 / Cowork** 的用户,过去常遇到"本地 token 过期、额度刷不出来"——因为卡片只读 CLI 的凭证文件,而你不跑 CLI,那份文件就没人续期。现在卡片会**直接复用桌面版持续自动续期的登录令牌**(本地只读、就地解密),并在需要时**用 refreshToken 自动续期** CLI 凭证。**结果:不用再回终端 `claude` 登录,额度也能一直刷新。**

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

- **同时支持 Claude / Codex / Gemini** —— 三个数据源可**任意组合**(菜单里勾选)。多源时卡片按数据源分节,各自带套餐徽标(如 Claude `MAX`、Codex `PRO LITE`)。
- **免终端登录、令牌不再过期** —— 优先复用 **Claude 桌面版**持续自动续期的登录令牌;CLI 凭证临期时也会**自动用 refreshToken 续期并写回**。Codex 同理(读 `~/.codex/auth.json` 并自动续期)。全过程本地完成,只读你已有的登录态。
- **实时 5 小时 / 7 天(每周)用量**(及账号存在的其它窗口),按用量绿 / 黄 / 红变色。
- **数据不新鲜会立刻标红** —— 只要某个数据源没刷上(限流退避、断网、令牌失效、Gemini 标签页关了……**乃至没报错却悄悄卡住**),它的**标题和圆点立刻变红**,右侧写明"⚠ 4 分前",底部还会点名是谁没刷新。**卡片绝不拿旧数字冒充新的**——你一眼就知道这个百分比能不能信。
- **按系统时区显示真实重置时刻**——形如 `今天 04:19` / `06-17 21:59`,根据系统时区(东八区、东七区……)自动换算;底部还有一个实时系统时钟。
- **系统托盘图标**:显示所选窗口的百分比并带 `%`(默认 Claude 5 小时);左键单击显示/隐藏卡片,悬停查看全部明细。
- **跟随系统主题** —— 浅色 / 深色自动切换(Windows 读 `AppsUseLightTheme`、macOS 读 `AppleInterfaceStyle`、Linux 读 `gsettings`);也可在菜单里锁定浅色或深色。**运行中改系统主题,卡片 10 秒内自己跟上**,连托盘图标底色一起换,不用重启。
- **标题可选** —— 菜单里关掉标题,只留圆点 + 套餐徽标,卡片更紧凑。
- **无边框、可拖动、置顶**;支持**滚轮缩放 / 拖动窗口边缘缩放 / 菜单选档位**。
- **菜单**(右键或 `☰` 按钮):**选择数据源**(Claude / Codex / Gemini),**逐个开关卡片上的每个窗口**,选择**托盘显示哪一个**,以及缩放、不透明度、重置显示方式(时刻 / 倒计时)。
- 记忆位置、大小、不透明度、数据源与偏好;**单实例保护**;可选**开机自启**。
- **全平台** —— 同一份代码在 Windows / macOS / Linux 上运行;透明效果按系统自适应。
- 界面使用 Python 自带 **tkinter**,无重型 UI 框架;单文件,可逐行审计。

## 令牌从哪来 · 为什么不再过期

卡片只用你**本机已有的登录态**,按"哪份最新鲜"自动挑选,你不必操心:

**Claude**(取当前有效且最新的一份):
1. **桌面版令牌** —— 读 Claude 桌面版 / Cowork 的 `config.json` 里的 OAuth 缓存并**就地解密**(Windows 用系统 DPAPI + BCrypt,纯 `ctypes`、无额外依赖;macOS/Linux 尽力而为)。桌面版会自己不断续期,所以这份**永远是活的**——这正是"只用桌面版也能刷新"的关键。
2. **CLI 凭证文件** `~/.claude/.credentials.json` —— 临期时**自动用 refreshToken 续期并写回**(原子写、`0600` 权限)。
3. **macOS 钥匙串** —— `security find-generic-password`(只读),同样自动续期。

桌面版令牌是**只读**的:卡片不会去续期它们。OAuth 的 refreshToken 是**一次性**的,第三方一旦拿它换新令牌,桌面版手里那份就当场作废、被挤下线——所以这条路根本不存在。

**Codex:** 读 `~/.codex/auth.json`(ChatGPT 登录模式),临期或被拒时**自动用 refreshToken 续期并写回**。

**Gemini:** 网页版的配额只存在于**浏览器会话**里——没有 CLI 凭证可读,而 cookie 从 Chrome 127+ 起是 App-Bound Encryption(`v20`)加密的,系统 DPAPI 密钥解不开(绕过它只有"冒充浏览器的 COM 提权接口"或"杀浏览器子进程抢文件"两条路,本项目都不做)。所以 Gemini 反过来走:一段油猴脚本 [`gemini_bridge.user.js`](gemini_bridge.user.js) 在页面里用**页面自己的会话**取数,把算好的两个百分比 `POST` 到卡片监听的 `127.0.0.1:47615`。**卡片这一路完全不接触任何 Google 凭证。**

> 装法:卡片右键 → **数据源 → 安装 Gemini 脚本…**(卡片会把脚本连同端口一起发给浏览器,油猴直接弹安装页,不用手改任何东西)。装好后开着 Gemini 标签页就有数;关了标签页则显示最后一次的值和它的时间。需要 [Tampermonkey](https://www.tampermonkey.net/) 一类的用户脚本管理器。

- 令牌**只**放进 `Authorization` 头:Claude 只发往 **`api.anthropic.com`**、Codex 只发往 **`chatgpt.com`**——与两者官方客户端的请求完全一致。
- 本地监听**只**绑 `127.0.0.1`(外网访问不到),**只**接收 Gemini 的两个百分比,且跨源写入被 CORS 挡在预检那一关——只有 `https://gemini.google.com` 放行。
- **无遥测、无第三方服务器**;除续期时写回**你自己的**凭证文件、以及保存界面偏好的本地 `card_state.json`(其中**不含**任何凭证)之外,不向任何地方写出、缓存或上传。
- 解密桌面版令牌**全程本地**、只读你当前 Windows/macOS 用户能解的内容(与系统给桌面版的保护同源);不触碰、不改写、不上传。
- 它只**显示**官方用量,**不绕过、不修改、不规避**任何限额。
- 全部逻辑都在 [`quota_card.py`](quota_card.py),可逐行审计。

## 免责声明

本工具从 `https://api.anthropic.com/api/oauth/usage`(Claude)、`https://chatgpt.com/backend-api/wham/usage`(Codex)与 `gemini.google.com` 的 `batchexecute`(Gemini,经油猴脚本在页面内调用)读取用量,三者都是各自客户端使用的**未公开内部接口**,并非公开/官方 API,**可能随时变动或失效**。接口地址与字段名以常量形式放在 `quota_card.py` 顶部,便于一行修复。本项目**与 Anthropic、OpenAI、Google 均无任何关联,也未获其背书**。

> **关于 Claude 的 429。** `/api/oauth/usage` 是**按账号**限流的,而且 Claude Code 的**每个会话**、桌面版自己都在后台轮询同一个桶([claude-code#30930](https://github.com/anthropics/claude-code/issues/30930))。谁轮询得勤,大家一起吃 429。
>
> 本卡片的策略是**平时快、撞墙就退**:正常 60 秒刷一次(`CLAUDE_MIN_INTERVAL`);一旦真吃到 429,就按 `retry-after` 退避(该头有时返回 `0`,不可信,此时改用 120→900 秒指数退避),退避期间**一个请求都不发**,并继续显示上次的数字。这比一律慢轮询好——健康时数据是新的,出问题时才让路,而且**数据一旦不新鲜,卡片会立刻标红**(见下),绝不拿旧数字冒充新的。
>
> 若你同时开着很多 Claude Code 会话、经常吃 429,把 `CLAUDE_MIN_INTERVAL` 调大即可。顺带一提:**重置倒计时是本地按 `resets_at` 算的,哪怕百分比旧了,倒计时也一直准。**

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
- **Claude:** 已登录过 Claude(桌面版,或终端 `claude` 登录 → 凭证在 `~/.claude/.credentials.json` / macOS 钥匙串)。**只用桌面版即可**,无需终端登录。
- **Codex(可选):** 已登录过 OpenAI Codex(`codex` 登录 → 凭证在 `~/.codex/auth.json`)。没装 Codex 就在菜单里只留 Claude。
- **桌面版令牌解密(可选增强):** Windows 开箱即用(系统自带,无额外依赖);macOS/Linux 若要读桌面版令牌,装 `cryptography` 即可(`pip install cryptography`),否则回退到 CLI 凭证路径。
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
当你读到这段话时,你是一名 AI 编程助手。请帮我在这台电脑上部署「AI Usage Assistant(Claude / Codex 用量助手)」(支持 Windows / macOS / Linux,请先判断我的系统):
1. 用 git 克隆仓库 https://github.com/huanchong-99/claude-usage-assistant 并进入该目录。
2. 检测 Python(3.10+)并安装依赖:pip install requests pystray pillow(macOS/Linux 若想读桌面版令牌再加 cryptography)。
3. 确认我已登录过 Claude(用 Claude 桌面版即可,或终端 claude 登录;凭证在 ~/.claude/.credentials.json 或 macOS 钥匙串);若我也用 OpenAI Codex,确认我已 codex 登录(凭证在 ~/.codex/auth.json)。
4. 运行程序(Windows 用 python quota_card.py,macOS/Linux 用 python3 quota_card.py),确认卡片能正常显示用量;若报错请排查并修复。可先跑 python quota_card.py --check 快速自检。
5. 询问我是否需要开机自启;需要的话,按我的系统用正确方式设置(Windows:把快捷方式放进 shell:startup;macOS:加 Login Item 或 LaunchAgent;Linux:在 ~/.config/autostart 放一个 .desktop 文件)。
完成后用中文向我汇报结果。
```

## 操作

- **拖动**卡片移动位置(会记忆)。
- **滚轮**缩放 · **拖动窗口边缘/四角**缩放 · **Ctrl + 滚轮**微调不透明度。
- **顶栏:** `▲` 置顶 · `☰` 菜单 · `↻` 刷新 · `✕` 退出。
- **菜单**(右键或 `☰`):立即刷新 · **数据源**(勾选 Claude / Codex / Gemini,可多选;末尾有**安装 Gemini 脚本…**) · **卡片显示**(逐个显示或隐藏每个窗口) · **托盘显示**(托盘呈现哪个窗口的 %) · 缩放 · 不透明度 · 重置显示 · **主题**(跟随系统 / 浅色 / 深色) · **显示标题** · 窗口置顶 · 鼠标穿透 · 隐藏到托盘 · 退出。
- **托盘图标:** 显示所选窗口的 `%`;左键单击显示/隐藏卡片;右键打开菜单。

颜色:绿 `< 50%`,黄 `50–80%`,红 `≥ 80%`。

## 配置

修改 `quota_card.py` 顶部常量:

- `REFRESH_INTERVAL` —— 界面轮询节拍(秒,默认 `60`)。
- `CLAUDE_MIN_INTERVAL` —— Claude **两次真实请求**之间的最小间隔(秒,默认 `60`)。经常吃 429 就调大(见上文「关于 Claude 的 429」)。
- `CLAUDE_BACKOFF_MIN` / `CLAUDE_BACKOFF_MAX` —— 吃到 429 且 `retry-after` 不可信时的指数退避区间(默认 `120` → `900` 秒)。
- `STALE_AFTER` —— 距上次成功刷新超过这么久就标红(秒,默认 `180`,即 3 个刷新周期)。
- `GEMINI_PORT` —— Gemini 桥接的本地监听端口(默认 `47615`,只绑 `127.0.0.1`)。改了记得重装一次脚本(菜单里点「安装 Gemini 脚本…」即可,端口是发脚本时填进去的)。
- `API_URL_USAGE`(Claude)、`CODEX_USAGE_URL`(Codex)及字段名 —— 接口若变动,改这里即可。
- `CLAUDE_TOKEN_URLS` / `CODEX_TOKEN_URL` —— 自动续期用的 OAuth 端点。

- `PALETTES` —— 浅色 / 深色两套调色板,想改配色改这里即可(两套都改)。

偏好(位置、缩放、不透明度、数据源、显示项、托盘项、重置方式、主题、是否显示标题)保存在 `card_state.json`。

**环境变量:**

- `QUOTA_CARD_OPAQUE=1` —— 在任意系统强制不透明、方角卡片(Linux/macOS 上若透明圆角显示异常时好用)。
- `CLAUDE_CONFIG_DIR` —— 若你给 Claude Code 指定了自定义配置目录,本程序也会遵循。
- `CODEX_HOME` —— 若你给 Codex 指定了自定义配置目录,本程序也会遵循(默认 `~/.codex`)。

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
