---
name: book-video-maker
description: 書單號爆款短影音生成器。背景圖由 Codex 內建的圖像生成工具（Codex OAuth 認證，免 API Key、走 ChatGPT 訂閱額度）預生，Python 腳本負責語音 (edge-tts) + 影片合成（hyperframes 或 ffmpeg/libx264 自動偵測）。當使用者要求生成「書單號」「書摘短影音」「金句影片」或指定書名做爆款短片時觸發。
---

# Book Video Maker 3.1 — Codex 圖像 + 雙引擎合成 Skill

書單爆款短影音生成器 — **圖像由 Codex 預生，腳本做語音 + 影片合成**

## 職責劃分

| 階段 | 負責方 | 工具 |
|---|---|---|
| 1. 背景圖生成 | **Codex 內建圖像工具** | Codex CLI 自帶的 image generation tool（Codex OAuth → ChatGPT 訂閱額度） |
| 2. 語音合成 | Python 腳本 | edge-tts |
| 3. 影片合成 | Python 腳本（引擎可插拔） | **預設 auto**：偵測到 Node 22+ 與 hyperframes 走 hyperframes，否則 fallback ffmpeg/libx264 |

**腳本不再呼叫任何雲端圖像 API**，所以也不需要 `OPENAI_API_KEY` / `ARK_API_KEY` 之類的設定。Codex OAuth 一次登入後（`codex login`），所有圖像生成都走訂閱額度，不另計費。

## 合成引擎

| 引擎 | 渲染棧 | 觸發條件 | 適合 |
|---|---|---|---|
| **hyperframes** ⭐ | HTML/CSS/JS → Puppeteer + FFmpeg → MP4 | Node ≥ 22 且 `hyperframes` 已裝（global 或 local） | 想要更花俏的動畫、轉場、字卡客製 |
| **ffmpeg** | 純 FFmpeg + libx264 + drawtext | FFmpeg 含 libx264 即可 | 輕量部署（Alpine 容器、低資源 server） |

預設 `--engine auto`：腳本會被動偵測（**不會自動安裝任何 npm 套件**）。偵測順序：

1. `hyperframes`：檢查 `node --version` ≥ 22，且 `hyperframes` 在 PATH 或 `./node_modules/.bin/` 內。
2. 上一步不通過 → 退 `ffmpeg`（檢查 `ffmpeg -encoders` 含 `libx264`）。
3. 兩個都不通過 → 列出原因並 exit 3。

要強制指定引擎：`--engine ffmpeg` 或 `--engine hyperframes`（強制時若不可用會立即報錯，不會 fallback）。

> ⚠️ **hyperframes 引擎標記為 experimental**——HTML/CSS schema 來自公開文件（README + quickstart + llms.txt），動畫和字幕語法可能會微調。建議先在 `who_moved_my_cheese.json`（16 句最短）跑通再用到長模板。

### 安裝 hyperframes（可選）

```bash
# 系統需求：Node.js >= 22
node --version  # 確認 ≥ v22

# 全局安裝（推薦，每個專案都能用）
npm install -g hyperframes

# 或專案本地安裝
npm install hyperframes
```

---

## Agent 執行流程（建議照做）

### Step 1 — 載入金句模板

```bash
# 內建模板（任選其一或自帶）:
templates/rich_dad_poor_dad.json     # 《穷爸爸富爸爸》 22 句
templates/who_moved_my_cheese.json   # 《谁动了我的奶酪》 16 句
templates/willpower.json             # 《自控力》 17 句
```

讀取 JSON，注意每條都有 `cn`(繁體中文字幕) / `en`(英文字幕) / `prompt`(背景圖 prompt) 三欄。內建模板的 `cn` 欄位（畫面字幕）已轉為**繁體中文**；語音則仍走 `zh-CN-YunxiNeural`（普通話）—— edge-tts 讀繁體輸入會自動以普通話發音，畫面字幕為繁體、語音為普通話為刻意設計。要換語音可帶 `--voice zh-TW-YunJheNeural`（台灣腔）等。

### Step 2 — 預先建立 run_dir

固定 run_dir 避免時間戳每次變動：

```bash
RUN_DIR="output/书名_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN_DIR"
```

### Step 3 — 批次預生背景圖

**推薦：直接跑 `scripts/predraw.sh`**（會自動逐句呼叫 `codex exec`，續跑友好）：

```bash
chmod +x scripts/predraw.sh
./scripts/predraw.sh templates/rich_dad_poor_dad.json "$RUN_DIR"
```

predraw.sh 行為：
- 對 quotes.json 每條 segment 呼叫一次 `codex exec`，請 Codex 用內建圖像生成工具生 1024x1536 JPEG
- 已存在且 > 1KB 的圖會 **skip**，所以中斷後重跑不會重複付費
- 失敗的圖不中斷整批，最後列出缺失索引並 exit 2

**手動逐句呼叫**（若要客製化 prompt 或繞過腳本）：

```bash
# 情境 A：你（執行 skill 的 agent）就是 Codex —— 直接呼叫你自己的圖像工具：
#   tool: <Codex 圖像生成工具>
#   args: { prompt, size: "1024x1536", outputFormat: "jpeg",
#           filename: "$RUN_DIR/bg_<NN>.jpg" }

# 情境 B：你是其他 agent（Claude Code / OpenClaw 等）—— 透過 codex exec 委派：
codex exec --dangerously-bypass-approvals-and-sandbox \
  "Generate an image with prompt: \"$PROMPT\". Size 1024x1536, JPEG. \
   Save to absolute path: $RUN_DIR/bg_05.jpg. \
   Use your built-in image generation tool. Do not call any HTTP API."
```

**檔名規則** (`generate.py:find_image` 嚴格依此尋找):
- `bg_00.jpg` ~ `bg_NN.jpg`（兩位數補零）
- 也接受 `.jpeg` / `.png` / `.webp` 副檔名
- 檔案 < 1KB 視為無效，會被當缺圖處理

### Step 4 — 執行合成腳本

```bash
# 預設：自動偵測引擎（推薦）
python scripts/generate.py \
  -b "穷爸爸富爸爸" \
  -a "罗伯特·清崎" \
  -q templates/rich_dad_poor_dad.json \
  --run-dir "$RUN_DIR"

# 強制使用 ffmpeg（向後相容）
python scripts/generate.py ... --engine ffmpeg

# 強制使用 hyperframes（需先 npm i -g hyperframes）
python scripts/generate.py ... --engine hyperframes
```

`--run-dir` 重用 Step 2 建好的目錄；腳本會從同一個目錄讀取 `bg_NN.jpg`。

若想另放圖片目錄，加 `--images-dir <path>`。

**hyperframes 引擎的副產物**：會在 `$RUN_DIR/hyperframes/` 內留下完整 HTML 專案（`meta.json` + `index.html` + `assets/`），可以用 `npx hyperframes preview`（在該目錄內）即時預覽，方便調整 CSS/動畫。

### Step 5 — 取得成品

```
$RUN_DIR/final.mp4    # 最終影片 (1080x1920, H.264 CRF 21, faststart)
$RUN_DIR/voices/      # 逐句語音 mp3
$RUN_DIR/seg_N.mp4    # 各分鏡 (除錯用)
```

---

## 缺圖時的行為

若 agent 漏生某張圖，腳本會**直接 exit 2** 並列印缺圖清單與每張的 prompt：

```
[ERROR] 缺少 3 張圖: [5, 12, 18]
======================================================================
[ACTION REQUIRED] 需要預先生成下列背景圖再執行本腳本：
目標目錄: output/书名_xxx
建議 image_generate 參數: size="1024x1536", count=1, outputFormat="jpeg"
檔名規則: bg_<兩位數編號>.jpg ...
  bg_05.jpg
    prompt: ...
======================================================================
```

Agent 看到此訊息應補生缺圖後**重新執行腳本（同一個 --run-dir）**，已生的圖會被沿用，不會重複付費。

---

## 系統需求

目標部署環境：**Linux** (Ubuntu / Debian / CentOS / Alpine 皆可)

- Python >= 3.8
- FFmpeg **必須含 libx264 (GPL)**：`ffmpeg -encoders | grep libx264` 應有輸出
  - Ubuntu/Debian: `sudo apt install -y ffmpeg`（官方套件已含 libx264）
  - Alpine: `apk add ffmpeg`
- `jq`（給 predraw.sh 解析 JSON 用）：`sudo apt install -y jq`
- Python 套件：`edge-tts`（腳本啟動時自動安裝）
- **Codex CLI** 已安裝並登入：
  ```bash
  # 安裝（依官方文件，這裡以通用方式示意）
  codex --version    # 確認已裝
  codex login        # 完成 OAuth (一次性, 之後讀 ~/.codex/auth.json)
  codex exec "say hi" # 煙霧測試
  ```
- **（可選）Node.js ≥ 22 + hyperframes**（解鎖 hyperframes 引擎；不裝會自動退 ffmpeg）：
  ```bash
  # Ubuntu/Debian (NodeSource)
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt install -y nodejs
  npm install -g hyperframes
  ```

## Linux 部署 (從零開始)

```bash
# 1. 解壓 skill 包
cd ~ && unzip book-video-maker.zip -d ~/skills/

# 2. 安裝系統依賴
sudo apt update
sudo apt install -y python3 python3-pip ffmpeg jq fonts-noto-cjk

# 3. 確認 Codex CLI
which codex && codex --version
codex login  # 首次

# 4. 賦予執行權限
cd ~/skills/book-video-maker
chmod +x scripts/predraw.sh

# 5. 煙霧測試（最短的模板）
RUN_DIR="output/cheese_smoke_$(date +%s)"
mkdir -p "$RUN_DIR"
./scripts/predraw.sh templates/who_moved_my_cheese.json "$RUN_DIR"
python3 scripts/generate.py \
    -b "谁动了我的奶酪" \
    -a "斯宾塞·约翰逊" \
    -q templates/who_moved_my_cheese.json \
    --run-dir "$RUN_DIR"

# 6. 成品
ls -la "$RUN_DIR/final.mp4"
```

### 字體授權注意

`fonts/` 內含：
- ✅ `NotoSansCJKsc-Bold.ttf` / `NotoSansCJKsc-Regular.ttf`（Apache 2.0，**Linux 商用安全**）
- ✅ `arial.ttf`（系統字體變體，自行確認授權）
- ⚠️ `msyhbd.ttf` / `msyh.ttf`（Microsoft YaHei，**Windows-only 授權，Linux 商用需移除或替換**）

若用於商業發佈，建議修改 `scripts/generate.py` 將 `msyhbd.ttf` / `msyh.ttf` 替換為 `NotoSansCJKsc-Bold.ttf` / `NotoSansCJKsc-Regular.ttf`。

---

## 影片參數（寫死，要改需動原始碼）

| 項目 | 值 |
|---|---|
| 解析度 | 1080×1920 (豎屏 9:16) |
| 幀率 | 30 fps |
| 編碼 | H.264 (libx264, preset=medium, CRF=21) |
| 音訊 | AAC 192k |
| 容器 | MP4 (+faststart 適合線上串流) |
| Ken Burns | 4 方向交替平移，相鄰不重複 |
| 字幕渐显 | 0.3 秒 |

---

## CLI 參數速查

| 參數 | 簡寫 | 說明 | 預設 |
|---|---|---|---|
| `--book` | `-b` | 書名 | 必填 |
| `--author` | `-a` | 作者 | 必填 |
| `--quotes` | `-q` | 金句 JSON | 內建 rich_dad_poor_dad.json |
| `--output` | `-o` | 輸出根目錄 | `output` |
| `--voice` | `-v` | edge-tts 語音 | `zh-CN-YunxiNeural` |
| `--rate` | `-r` | 語速 | `+0%` |
| `--images-dir` | `-I` | 預生圖目錄 | 同 run_dir |
| `--run-dir` | — | 重用既有 run_dir | 新建時間戳目錄 |
| `--engine` | `-e` | 合成引擎: `auto` / `ffmpeg` / `hyperframes` | `auto` |

---

**版本**: 3.1.1
**更新**: 2026-05-19
**作者**: QClaw

## 變更紀錄

- **3.1.1** (2026-05-19)
  - 三個內建模板 (`rich_dad_poor_dad.json` / `who_moved_my_cheese.json` / `willpower.json`) 的 `cn` 字幕全部轉為繁體中文（畫面字幕用）。
  - 預設語音 `zh-CN-YunxiNeural` 維持不變；繁體輸入由 edge-tts 自動以普通話發音。
  - hyperframes 引擎輸出 HTML 的 `lang` 屬性由 `zh-CN` 改為 `zh-TW`（描述字幕語系）。
- **3.1.0** (2026-05-17)
  - 加入 `--engine` 旗標（`auto` / `ffmpeg` / `hyperframes`），預設 `auto`。
  - 新增 hyperframes 引擎 (`scripts/engines/hyperframes_engine.py`，experimental)：產生 HTML/CSS/JS 專案後呼叫 `npx hyperframes render`。
  - 把原本 ffmpeg 合成段抽到 `scripts/engines/ffmpeg_engine.py`，行為與 3.0 一致。
  - 偵測為被動式：沒裝 Node/hyperframes 也不會自動安裝，會 fallback 到 ffmpeg。
- **3.0.0** — Codex OAuth 圖像 + 本地語音/影片合成 baseline。
