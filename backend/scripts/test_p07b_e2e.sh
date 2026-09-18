#!/usr/bin/env bash
# P0-7-B 端到端测试：上传 → MinerU 异步解析 → 轮询 → 重解析 → 删除
#
# 前置：
#   1. Redis 在跑（deploy/docker-compose.dev.yml）
#   2. backend/.env 配好 MINERU_PYTHON
#   3. uvicorn app.main:app（默认 8765）
#   4. arq app.worker.WorkerSettings
#
# 用法：bash scripts/test_p07b_e2e.sh [pdf路径] [最大轮询次数]
set -uo pipefail

BASE=${BASE:-http://127.0.0.1:8765/api/v1}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
STORAGE_DIR="$BACKEND_DIR/${STORAGE_ROOT:-storage}"
PDF=${1:-/tmp/p07b_test.pdf}
MAX_POLL=${2:-60}   # 最多轮询次数（每次 3s）
EMAIL="p07b_$(date +%s)@test.com"

jqp() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval('d'+sys.argv[1]))" "$1"; }

echo "=== 0. 前置检查 ==="
[ -f "$PDF" ] || { echo "❌ 测试文件不存在: $PDF"; exit 1; }
echo "文件: $PDF ($(stat -c%s "$PDF") bytes)"
curl -sf $BASE/health > /dev/null || { echo "❌ 后端未启动"; exit 1; }
echo "✓ 后端健康"

echo
echo "=== 1. 注册 + 建项目 ==="
TOKEN=$(curl -s -X POST $BASE/auth/register -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"testpass123\",\"full_name\":\"P07B\",\"default_role\":\"owner\"}" \
    | jqp "['access_token']")
PROJECT_ID=$(curl -s -X POST $BASE/projects -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name":"P07B测试项目","role":"owner"}' | jqp "['id']")
echo "✓ project_id=$PROJECT_ID"

echo
echo "=== 2. 上传 PDF（应自动入队解析） ==="
UP=$(curl -s -X POST "$BASE/projects/$PROJECT_ID/documents" \
    -H "Authorization: Bearer $TOKEN" \
    -F "file=@$PDF" \
    -F "document_type=contract" \
    -F "title=P07B 测试合同")
DOC_ID=$(echo "$UP" | jqp "['id']")
echo "$UP" | python3 -m json.tool | head -12
echo "✓ doc_id=$DOC_ID"

echo
echo "=== 3. 轮询解析状态（最多 ${MAX_POLL} 次 × 3s） ==="
STATUS=""
for i in $(seq 1 "$MAX_POLL"); do
    DETAIL=$(curl -s "$BASE/projects/$PROJECT_ID/documents/$DOC_ID" -H "Authorization: Bearer $TOKEN")
    STATUS=$(echo "$DETAIL" | jqp "['parse_status']")
    printf "  [%02d] status=%s\n" "$i" "$STATUS"
    if [ "$STATUS" = "parsed" ] || [ "$STATUS" = "failed_parse" ]; then break; fi
    sleep 3
done

echo
echo "=== 4. 解析结果 ==="
echo "$DETAIL" | python3 -c "
import json,sys
d = json.load(sys.stdin)
print('parse_status  :', d['parse_status'])
print('parse_error   :', (d['parse_error'] or '')[:200])
pc = d.get('parsed_content')
if pc:
    print('  pages       :', pc.get('page_count'))
    print('  chars       :', pc.get('markdown_chars'))
    print('  elapsed_sec :', pc.get('elapsed_sec'))
    print('  tier        :', pc.get('tier'))
    print('  parsed_dir  :', pc.get('parsed_dir'))
    print('  markdown[:120]:', repr((pc.get('markdown') or '')[:120]))
"

echo
echo "=== 5. 落盘产物检查 ==="
PARSED_DIR="$STORAGE_DIR/parsed/$PROJECT_ID/$DOC_ID"
ls -la "$PARSED_DIR" 2>&1 | head -12

echo
echo "=== 6. 重解析 ==="
curl -s -X POST "$BASE/projects/$PROJECT_ID/documents/$DOC_ID/reparse" \
    -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo
echo "=== 7. 等待重解析完成 ==="
for i in $(seq 1 "$MAX_POLL"); do
    S=$(curl -s "$BASE/projects/$PROJECT_ID/documents/$DOC_ID" -H "Authorization: Bearer $TOKEN" | jqp "['parse_status']")
    printf "  [%02d] status=%s\n" "$i" "$S"
    if [ "$S" = "parsed" ] || [ "$S" = "failed_parse" ]; then break; fi
    sleep 3
done

echo
echo "=== 8. 删除档案（应清理 DB + 源文件 + 产物） ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
    "$BASE/projects/$PROJECT_ID/documents/$DOC_ID" -H "Authorization: Bearer $TOKEN")
echo "DELETE 返回: $CODE (期望 204)"
echo "删除后列表:"
curl -s "$BASE/projects/$PROJECT_ID/documents" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
echo "源文件是否清除: $([ -f "$STORAGE_DIR/projects/$PROJECT_ID/$DOC_ID.pdf" ] && echo '❌ 仍存在' || echo '✓ 已清除')"
echo "产物目录是否清除: $([ -d "$PARSED_DIR" ] && echo '❌ 仍存在' || echo '✓ 已清除')"

echo
echo "=== 完成 ==="
