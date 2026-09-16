#!/usr/bin/env bash
# 把当前提交部署到 NAS 上的 AstrBot 插件目录并重载插件。
#
# 流程（与 docs/RELEASE.md 一致，NAS 部署独立于 git push）：
#   1. 本地打 bundle（只传提交，不依赖远端网络）
#   2. 远端 git fetch + merge --ff-only（不做 reset --hard，避免覆盖 NAS 侧改动）
#   3. 调用面板接口重载插件，并核对版本与插件日志
#
# 用法：
#   tools/deploy_nas.sh                 # 部署当前分支 HEAD
#   tools/deploy_nas.sh main            # 部署指定分支
#   REF=HEAD~1 tools/deploy_nas.sh      # 环境变量覆盖
#
# 环境变量：
#   REF        要部署的 ref（默认当前分支）
#   SSH_KEY    SSH 私钥（默认 ~/.ssh/lirating_nas）
#   SSH_HOST   目标主机（默认 loicawu@192.168.2.198）
#   SSH_PORT   SSH 端口（默认 9707）
#   PLUGIN_DIR NAS 上的插件目录
#   ASTRBOT_BASE 面板地址（默认 http://192.168.2.198:6185）
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REF="${REF:-$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/lirating_nas}"
SSH_HOST="${SSH_HOST:-loicawu@192.168.2.198}"
SSH_PORT="${SSH_PORT:-9707}"
PLUGIN_DIR="${PLUGIN_DIR:-/volume2/docker/qqbot/data/plugins/astrbot_plugin_image_vote}"
ASTRBOT_BASE="${ASTRBOT_BASE:-http://192.168.2.198:6185}"
BUNDLE="${TMPDIR:-/tmp}/lirating-deploy.bundle"

say() { printf '\n== %s\n' "$*"; }

say "1/4 本地打包 $REF"
git -C "$REPO_DIR" bundle create "$BUNDLE" "$REF" 2>&1 | tail -1
COMMIT="$(git -C "$REPO_DIR" rev-parse --short "$REF")"
VERSION="$(git -C "$REPO_DIR" show "$REF:metadata.yaml" | awk '/^version:/ {print $2}')"
echo "提交 $COMMIT，版本 $VERSION"

say "2/4 快进部署到 $SSH_HOST:$PLUGIN_DIR"
ssh -i "$SSH_KEY" -p "$SSH_PORT" -o BatchMode=yes "$SSH_HOST" "cat > /tmp/lirating-deploy.bundle; cd '$PLUGIN_DIR' && git fetch /tmp/lirating-deploy.bundle '$REF' >/dev/null 2>&1 && git merge --ff-only FETCH_HEAD && rm -f /tmp/lirating-deploy.bundle" < "$BUNDLE"
rm -f "$BUNDLE"

say "3/4 核对远端文件"
ssh -i "$SSH_KEY" -p "$SSH_PORT" -o BatchMode=yes "$SSH_HOST" "cd '$PLUGIN_DIR' && git log --oneline -1 && grep -E '^version' metadata.yaml && git status --porcelain | wc -l"

say "4/4 重载插件并检查日志"
python3 - "$ASTRBOT_BASE" "$VERSION" <<'PY'
import json, sys, time, urllib.error, urllib.request

base, version = sys.argv[1], sys.argv[2]
password = __import__('os').environ.get('ASTRBOT_PASSWORD')
if not password:
    print('跳过面板重载：未设置 ASTRBOT_PASSWORD（重载需要面板管理员密码）')
    sys.exit(0)

def call(path, payload=None, token=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.status, response.read().decode()

_, body = call('/api/auth/login', {'username': 'astrbot', 'password': password})
token = json.loads(body)['data']['token']
_, body = call('/api/v1/plugins/reload', {'plugin_id': 'astrbot_plugin_image_vote'}, token=token, method='POST')
print('重载响应：' + body[:120])
time.sleep(5)
_, logs = call('/api/v1/logs/history?limit=200', token=token)
payload = json.loads(logs)
data = payload.get('data', payload)
entries = data.get('logs') if isinstance(data, dict) else data
lines = [(item.get('data') if isinstance(item, dict) else str(item)) or '' for item in (entries or [])]
loaded = [line for line in lines if 'astrbot_plugin_image_vote (' in line and 'Loading' in line or 'Plugin astrbot_plugin_image_vote (' in line]
errors = [line for line in lines if 'astrbot_plugin_image_vote' in line and ('ERROR' in line or 'Traceback' in line)]
print('加载日志：' + (loaded[-1][:160] if loaded else '未在最近日志中找到加载行'))
print('插件报错行：%d' % len(errors))
if version not in (loaded[-1] if loaded else ''):
    print('注意：日志中的版本与本次部署版本不一致，请确认重载是否生效')
PY

say "完成：$COMMIT（$VERSION）已部署并重载"
