#!/usr/bin/env bash
# predraw.sh — 批次呼叫 Codex 內建圖像生成工具，預生背景圖
#
# 用法:
#   ./scripts/predraw.sh <quotes.json> <run_dir>
#
# 範例:
#   ./scripts/predraw.sh templates/rich_dad_poor_dad.json output/穷爸爸富爸爸_run1
#
# 依賴: bash, jq, codex CLI (已 `codex login`)
# 行為:
#   - 對 quotes.json 每一條 segment 呼叫一次 codex exec
#   - 已存在且 > 1KB 的圖會被跳過 (續跑友好)
#   - 失敗的圖不會中斷整個批次，最後列出缺圖清單

set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <quotes.json> <run_dir>" >&2
    exit 1
fi

QUOTES_FILE="$1"
RUN_DIR="$2"

# 依賴檢查
for cmd in jq codex; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "[ERROR] 缺少依賴: $cmd" >&2
        exit 1
    fi
done

if [[ ! -f "$QUOTES_FILE" ]]; then
    echo "[ERROR] 找不到 quotes 檔: $QUOTES_FILE" >&2
    exit 1
fi

mkdir -p "$RUN_DIR"
RUN_DIR_ABS="$(cd "$RUN_DIR" && pwd)"

count=$(jq 'length' "$QUOTES_FILE")
echo "============================================================"
echo "predraw.sh — 預生 $count 張背景圖"
echo "  quotes:  $QUOTES_FILE"
echo "  run_dir: $RUN_DIR_ABS"
echo "============================================================"

missing=()
skipped=0
generated=0

for ((i=0; i<count; i++)); do
    idx=$(printf '%02d' "$i")
    out="$RUN_DIR_ABS/bg_$idx.jpg"

    if [[ -f "$out" && $(stat -c%s "$out" 2>/dev/null || stat -f%z "$out" 2>/dev/null || echo 0) -gt 1000 ]]; then
        echo "[$((i+1))/$count] skip (exists): bg_$idx.jpg"
        skipped=$((skipped+1))
        continue
    fi

    prompt=$(jq -r ".[$i].prompt" "$QUOTES_FILE")
    if [[ -z "$prompt" || "$prompt" == "null" ]]; then
        echo "[$((i+1))/$count] [WARN] segment[$i] 缺 prompt 欄位，跳過"
        missing+=("$i")
        continue
    fi

    echo "[$((i+1))/$count] generating: bg_$idx.jpg"
    echo "    prompt: ${prompt:0:80}..."

    if codex exec --dangerously-bypass-approvals-and-sandbox \
        "Generate an image with the following prompt: \"$prompt\". \
Size: 1024x1536 (portrait 2:3). Output format: JPEG. \
Save the image to this exact absolute path: $out. \
Use your built-in image generation tool. Do NOT call any HTTP API directly. \
After saving, reply only with the saved file path." \
        >/dev/null 2>&1; then

        if [[ -f "$out" && $(stat -c%s "$out" 2>/dev/null || stat -f%z "$out" 2>/dev/null || echo 0) -gt 1000 ]]; then
            echo "    [OK] $(du -h "$out" | cut -f1)"
            generated=$((generated+1))
        else
            echo "    [FAIL] codex exec 完成但檔案未生成或過小"
            missing+=("$i")
        fi
    else
        echo "    [FAIL] codex exec 退出碼非 0"
        missing+=("$i")
    fi
done

echo "============================================================"
echo "完成: 已存在 $skipped 張, 新生成 $generated 張, 缺失 ${#missing[@]} 張"
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "缺失索引: ${missing[*]}"
    echo "請手動處理或重跑本腳本 (已生成的會跳過)"
    exit 2
fi
echo "============================================================"
echo "下一步:"
echo "  python scripts/generate.py -b 书名 -a 作者 -q $QUOTES_FILE --run-dir $RUN_DIR_ABS"
echo "============================================================"
