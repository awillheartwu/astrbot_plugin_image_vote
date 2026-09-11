#!/usr/bin/env bash
# NAS 现场探针：在装有 AstrBot 的宿主机上运行（需要 sudo docker 权限）。
#
# 用法（在 NAS 上的仓库目录内执行）：
#   sudo bash tools/nas_probe.sh direct     # 直接写宿主的绑定挂载 data/plugins，不需要 docker 权限
#   sudo bash tools/nas_probe.sh facts      # 只读事实 + 容器内 API 探针，不修改任何东西
#   sudo bash tools/nas_probe.sh install    # 通过 docker 把主插件与探针插件复制进容器
#   sudo bash tools/nas_probe.sh logs       # 抓取插件加载与 [IMAGE_VOTE_PROBE] 日志
#   sudo bash tools/nas_probe.sh all        # facts + install，并打印后续步骤
#
# 环境变量：
#   CONTAINER=astrbot               指定容器名（默认自动探测名字里带 astrbot 的容器）
#   DATA_DIR=/mnt/docker/astrbot/data     direct 写入的宿主 data 目录（指向 AstrBot 的 data）
#   REPORT=<路径>                   输出文件（默认 <仓库>/probe-report-<动作>-<时间戳>.txt）
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="${CONTAINER:-}"
ACTION="${1:-facts}"
REPORT="${REPORT:-$REPO_DIR/probe-report-$ACTION-$(date +%Y%m%d-%H%M%S).txt}"

section() { printf '\n\n===== %s =====\n' "$*"; }
run() { printf '\n$ %s\n' "$*"; "$@" 2>&1 || printf '[退出码 %s]\n' "$?"; }
shell_in() { run docker exec "$CONTAINER" sh -lc "$1"; }

detect_container() {
  if [ -n "$CONTAINER" ]; then
    echo "使用容器（来自环境变量）：$CONTAINER"
    return 0
  fi
  CONTAINER="$(docker ps --format '{{.Names}}' | grep -i astrbot | head -n 1)"
  if [ -z "$CONTAINER" ]; then
    echo "找不到 astrbot 容器：请用 CONTAINER=<容器名> 重跑，或用 docker ps 确认容器名。"
    return 1
  fi
  echo "使用容器（自动探测）：$CONTAINER"
}

cmd_facts() {
  section "容器列表"
  run docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
  section "镜像与重启策略"
  run docker inspect "$CONTAINER" --format 'image={{.Config.Image}} restart={{.HostConfig.RestartPolicy.Name}}'
  section "挂载映射（宿主 => 容器）"
  run docker inspect "$CONTAINER" --format '{{range .Mounts}}{{.Type}} rw={{.RW}} {{.Source}} => {{.Destination}}{{"\n"}}{{end}}'
  section "容器内环境"
  shell_in 'whoami; python3 -V; which python3; ls -d /AstrBot /app 2>/dev/null'
  run docker exec "$CONTAINER" python3 -c "import astrbot, importlib.metadata as m, sys; print('python', sys.version.split()[0]); print('astrbot_file', astrbot.__file__); print('astrbot_version', m.version('astrbot'))"
  run docker exec "$CONTAINER" python3 -c "import PIL; print('Pillow', PIL.__version__)"
  section "容器内 plugins / plugin_data 目录"
  shell_in 'find / -maxdepth 5 -type d \( -name plugins -o -name plugin_data \) 2>/dev/null | head -10'
  section "容器内 API 探针（只读）"
  if docker cp "$REPO_DIR/tools/astrbot_api_probe.py" "$CONTAINER:/tmp/astrbot_api_probe.py" >/dev/null 2>&1; then
    run docker exec "$CONTAINER" python3 /tmp/astrbot_api_probe.py
  else
    echo "[docker cp 失败，跳过 API 探针]"
  fi
}

find_plugins_dir() {
  docker exec "$CONTAINER" sh -lc 'for d in /AstrBot/data/plugins /app/data/plugins /data/plugins; do [ -d "$d" ] && { echo "$d"; exit 0; }; done; find / -maxdepth 5 -type d -path "*/data/plugins" 2>/dev/null | head -n 1'
}

cmd_install() {
  local plugins_dir
  plugins_dir="$(find_plugins_dir)"
  if [ -z "$plugins_dir" ]; then
    echo "找不到容器内 plugins 目录，请先用 facts 确认路径。"
    return 1
  fi
  echo "容器内插件目录：$plugins_dir"
  section "复制主插件"
  if ( cd "$REPO_DIR" && tar cf - --exclude='.git' --exclude='__pycache__' --exclude='probe-report*.txt' . ) \
      | docker exec -i "$CONTAINER" sh -lc "mkdir -p '$plugins_dir/astrbot_plugin_image_vote' && tar xf - -C '$plugins_dir/astrbot_plugin_image_vote'"; then
    echo "已复制 -> $plugins_dir/astrbot_plugin_image_vote"
  else
    echo "[主插件复制失败]"
  fi
  section "复制探针插件"
  if ( cd "$REPO_DIR/tools/probe_plugin" && tar cf - . ) \
      | docker exec -i "$CONTAINER" sh -lc "mkdir -p '$plugins_dir/astrbot_plugin_image_vote_probe' && tar xf - -C '$plugins_dir/astrbot_plugin_image_vote_probe'"; then
    echo "已复制 -> $plugins_dir/astrbot_plugin_image_vote_probe"
  else
    echo "[探针插件复制失败]"
  fi
  section "容器内结果"
  shell_in "ls -l '$plugins_dir'; echo ---; ls -l '$plugins_dir/astrbot_plugin_image_vote' | head -20"
}

cmd_direct() {
  local data_dir="${DATA_DIR:-/mnt/docker/astrbot/data}"
  local plugins_dir="$data_dir/plugins"
  section "直接写入绑定挂载目录（不需要 docker 权限）"
  echo "data 目录：$data_dir"
  if [ ! -d "$data_dir" ]; then
    echo "目录不存在：${data_dir}（可用 DATA_DIR=<路径> 重跑）"
    return 1
  fi
  run mkdir -p "$plugins_dir"
  section "主插件 -> $plugins_dir/astrbot_plugin_image_vote"
  ( cd "$REPO_DIR" && tar cf - --exclude='.git' --exclude='__pycache__' --exclude='probe-report*.txt' . ) \
    | ( mkdir -p "$plugins_dir/astrbot_plugin_image_vote" && cd "$plugins_dir/astrbot_plugin_image_vote" && tar xf - ) \
    && echo "已写入主插件"
  run sh -c "ls -l '$plugins_dir/astrbot_plugin_image_vote' | head -20"
  section "探针插件 -> $plugins_dir/astrbot_plugin_image_vote_probe"
  ( cd "$REPO_DIR/tools/probe_plugin" && tar cf - . ) \
    | ( mkdir -p "$plugins_dir/astrbot_plugin_image_vote_probe" && cd "$plugins_dir/astrbot_plugin_image_vote_probe" && tar xf - ) \
    && echo "已写入探针插件"
  run sh -c "ls -l '$plugins_dir'"
}

cmd_logs() {
  section "最近 500 行容器日志"
  run docker logs --tail 500 "$CONTAINER"
  section "关键行过滤"
  run sh -c "docker logs --tail 500 '$CONTAINER' 2>&1 | grep -n -E 'IMAGE_VOTE_PROBE|image_vote|Traceback|Error|error' | tail -60"
}

cmd_next_steps() {
  section "下一步"
  cat <<'TXT'
1. 打开 AstrBot WebUI -> 插件管理，确认出现 astrbot_plugin_image_vote 和 astrbot_plugin_image_vote_probe，然后重载插件（或 docker restart <容器>）。
2. 重载后等 30 秒，执行：sudo bash tools/nas_probe.sh logs
3. 在测试群先发一条普通消息，再引用任意消息发送 4，然后再次执行 logs。
4. 把仓库目录下生成的 probe-report.txt 拖进 Codex 对话。
TXT
}

main() {
  local action="$1"
  if [ "$action" != "direct" ] && ! command -v docker >/dev/null 2>&1; then
    echo "本机没有 docker 命令（facts/install/logs 需要 docker，direct 不需要）。"
    return 1
  fi
  case "$action" in
    direct) cmd_direct ;;
    facts) detect_container && cmd_facts ;;
    install) detect_container && cmd_install ;;
    logs) detect_container && cmd_logs ;;
    all) detect_container && cmd_facts && cmd_install && cmd_next_steps ;;
    *) echo "未知参数：${action}（可用：direct / facts / install / logs / all）"; return 2 ;;
  esac
}

main "$ACTION" 2>&1 | tee "$REPORT"
printf '\n输出已保存到：%s\n' "$REPORT"
printf '如果使用了 sudo，文件属主是 root，读取不受影响。\n'
