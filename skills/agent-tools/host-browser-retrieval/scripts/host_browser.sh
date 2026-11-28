#!/usr/bin/env bash
# host_browser.sh — 从 WSL 驱动宿主机 Windows Edge 做网页检索。
#
# 机制：Windows 侧 Edge 用独立 profile 开 CDP（只绑 127.0.0.1），Windows 侧 Node
# 执行 edge_cdp.mjs 连本地端口，WSL 通过 PowerShell interop 调用并把结果读回 stdout。
# 之所以不让 WSL 直连：Edge 忽略 --remote-debugging-address，端口只绑 Windows 回环。
#
# 边界：只操作本 skill 自己的独立 profile 实例，绝不触碰用户正在使用的 Edge。
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_MJS="$SKILL_ROOT/scripts/edge_cdp.mjs"
CFG="${HOST_BROWSER_CONFIG:-${HERMES_HOME:-$HOME/.hermes}/host-browser.json}"
PS_EXE="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
[ -x "$PS_EXE" ] || PS_EXE="powershell.exe"
TIMEOUT_DEFAULT="${HOST_BROWSER_TIMEOUT:-150}"

die() { echo "ERROR: $*" >&2; exit 1; }

cfg() { [ -f "$CFG" ] || return 0
  python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get(sys.argv[2], "") or "")
except Exception:
    pass' "$CFG" "$1"; }

# 需要进入 PowerShell 单引号字面量的值：拒绝单引号与换行，其余原样（反斜杠在单引号内是字面量）。
psq() {
  case "$1" in
    *"'"*|*$'\n'*|*$'\r'*) die "不安全的配置值（含单引号或换行），拒绝执行: $1" ;;
  esac
  printf "'%s'" "$1"
}

ps() { timeout "$TIMEOUT_DEFAULT" "$PS_EXE" -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $1" 2>&1 | tr -d '\r'; }

win_query() { ps "$1" | tail -1 | tr -d '\n'; }

WINUSER="${HOST_BROWSER_WINUSER:-$(cfg winuser)}"
[ -n "$WINUSER" ] || WINUSER="$(win_query '$env:USERNAME')"
[[ "$WINUSER" =~ ^[A-Za-z0-9._-]+$ ]] || die "Windows 用户名不合法: $WINUSER"

PORT="$(cfg port)";   PORT="${PORT:-9222}"
[[ "$PORT" =~ ^[0-9]{1,5}$ ]] || die "port 必须是 1-5 位数字: $PORT"
UD="$(cfg user_data_dir)"; UD="${UD:-C:\\Users\\$WINUSER\\AppData\\Local\\edge-cdp}"
EDGE="${HOST_BROWSER_EDGE:-$(cfg edge_path)}"
PROXY="$(cfg proxy)"
NODE="$(cfg node_path)"; NODE="${NODE:-node}"
CACHE_WIN="C:\\Users\\$WINUSER\\AppData\\Local\\host-browser-retrieval"
CACHE_WSL="/mnt/c/Users/$WINUSER/AppData/Local/host-browser-retrieval"

if [ -z "$EDGE" ]; then
  for c in "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
           "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe"; do
    if [ -f "$c" ]; then
      EDGE="C:\\$(printf '%s' "${c#/mnt/c/}" | tr '/' '\\')"
      break
    fi
  done
fi
[ -n "$EDGE" ] || die "未找到 msedge.exe，请在 $CFG 里设 edge_path"

# 配置值进入 PowerShell 命令前统一校验：含单引号/换行即拒绝（避免把配置当代码执行）。
for v in "$UD" "$EDGE" "$NODE" "$PROXY"; do
  case "$v" in
    *"'"*|*$'\n'*|*$'\r'*) die "配置值含单引号或换行，拒绝使用: $v" ;;
  esac
done

# 防御：绝不把真实 Edge profile 当成本 skill 的实例（否则 close 会去关用户自己的浏览器）。
case "$UD" in
  *"Microsoft\Edge\User Data"*|*"Microsoft/Edge/User Data"*) die "user_data_dir 指向真实 Edge profile，拒绝使用: $UD" ;;
esac

# 归属谓词：--user-data-dir 的值必须整体等于本 profile（带引号，或无引号且后接空白/结尾）。
# 纯子串包含会把 edge-cdp2 / "edge-cdp [t1]" / hb-r2-9222 这类同前缀 profile 误认成自己，
# 导致 status 说谎、ensure/子命令驱动别人的实例、close 连带关掉别人的实例。
UD_RE="$(python3 -c 'import re,sys
e = re.escape(sys.argv[1])
print("--user-data-dir=(?:\"%s\"|%s(?=\\s|$))" % (e, e))' "$UD")"

# 脚本复制到 Windows 侧运行：不依赖 \\wsl.localhost UNC 与发行版名探测。
sync_script() {
  mkdir -p "$CACHE_WSL"
  cmp -s "$SRC_MJS" "$CACHE_WSL/edge_cdp.mjs" || cp "$SRC_MJS" "$CACHE_WSL/edge_cdp.mjs"
}

# 归属判定用参数边界匹配（见 UD_RE）：既避开 -like 的通配符语义，也避开 -Contains 的前缀误认。
our_pids() {
  ps "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { \$_.CommandLine -and \$_.CommandLine -match $(psq "$UD_RE") } | Select-Object -ExpandProperty ProcessId"
}
count_lines() { sed '/^[[:space:]]*$/d' | wc -l | tr -d ' '; }
our_count() { our_pids | count_lines; }
is_listening() { [ "$(win_query "if (Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue) { 'yes' } else { 'no' }")" = "yes" ]; }

# 监听者必须是本配置对应的 profile 实例：只看「端口有人听」，会把外部占用或另一个 profile 当成就绪。
listener_owns_ud() {
  win_query "try { \$c = Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction Stop | Select-Object -First 1; \$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + \$c.OwningProcess) -ErrorAction Stop; if (\$p.CommandLine -and \$p.CommandLine -match $(psq "$UD_RE")) { 'yes' } else { 'no' } } catch { 'no' }"
}

# 端口监听进程的 pid（DevTools 端口由浏览器主进程持有）。
port_owner_pid() { win_query "try { (Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction Stop | Select-Object -First 1).OwningProcess } catch { '' }"; }

# 关实例：pred 决定作用范围（port=仅端口持有进程 / all=本 profile 全部）。先优雅关窗，残留再终止。
close_by() {
  local pred
  if [ "$1" = all ]; then
    pred="\$_.CommandLine -and \$_.CommandLine -match $(psq "$UD_RE")"
  else
    pred="\$_.ProcessId -eq $2"
  fi
  ps "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $pred } | ForEach-Object { try { (Get-Process -Id \$_.ProcessId -ErrorAction Stop).CloseMainWindow() | Out-Null } catch {} }" >/dev/null
  sleep 3
  ps "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $pred } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" >/dev/null
}

launch() {
  # 值用内嵌双引号包裹：Start-Process -ArgumentList 拼接时不加引号，路径含空格会被拆成多个参数。
  local args="'--remote-debugging-port=$PORT','--user-data-dir=\"$UD\"','--no-first-run','--no-default-browser-check','about:blank'"
  if [ -n "$PROXY" ]; then psq "$PROXY" >/dev/null; args="'--proxy-server=\"$PROXY\"',$args"; fi
  ps "Start-Process -FilePath $(psq "$EDGE") -ArgumentList $args" >/dev/null
  for _ in $(seq 1 20); do is_listening && return 0; sleep 1; done
  die "Edge 启动后 $PORT 端口未监听（检查 user_data_dir 是否为非默认目录）"
}

run() {
  sync_script
  # 参数经 stdin 传 JSON：PowerShell 5.1 向原生命令传参会剥掉双引号，含引号的表达式会被静默改写。
  # node 未能启动时 $LASTEXITCODE 不会被赋值：先置空再判定，避免把「命令不存在」当成成功。
  local json
  json="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1:]))' "$@")"
  printf '%s' "$json" | ps "\$LASTEXITCODE=\$null; & $(psq "$NODE") $(psq "$CACHE_WIN\\edge_cdp.mjs") --stdin-args --port $PORT; if (\$null -eq \$LASTEXITCODE) { Write-Error 'node 未能启动，检查 node_path'; exit 1 } else { exit \$LASTEXITCODE }"
}

case "${1:-status}" in
  status)
    echo "port=$PORT config=$CFG"
    echo "edge=$EDGE"
    echo "user_data_dir=$UD"
    echo "proxy=${PROXY:-<none>}"
    if is_listening; then
      owns="$(listener_owns_ud)"
      ours="$(our_count)"
      total="$(win_query "(Get-Process msedge -ErrorAction SilentlyContinue | Measure-Object).Count")"
      echo "cdp_listening=yes"
      echo "listener_is_ours=$owns"
      echo "our_instances=$ours"
      echo "msedge_total_processes=$total"
      echo "user_edge_windows=$((total - ours))"
      [ "$owns" = yes ] || echo "WARNING: 端口 $PORT 的监听者不是本配置对应的 profile，拒绝驱动"
    else
      echo "cdp_listening=no"
      echo "our_instances=0"
      echo "msedge_total_processes=$(win_query "(Get-Process msedge -ErrorAction SilentlyContinue | Measure-Object).Count")"
    fi
    ;;
  ensure)
    if is_listening; then
      [ "$(listener_owns_ud)" = yes ] || die "端口 $PORT 已被其它进程占用（可能是另一个 profile 的 host-browser-retrieval 实例），请换 port 或先处理占用者"
      echo "already_listening port=$PORT"
    else
      launch && echo "launched port=$PORT"
    fi
    ;;
  close)
    case "${2:-}" in
      "")    SCOPE=port ;;
      --all) SCOPE=all ;;
      *)     echo "usage: $0 close [--all]" >&2; exit 2 ;;
    esac
    if [ "$SCOPE" = all ]; then
      before="$(our_count)"
      if [ "$before" -eq 0 ]; then echo "no_our_instances"; exit 0; fi
      close_by all
    else
      # 默认只关本端口实例：同一 profile 的其它端口实例可能属于另一个并发会话，默认不替对方决定。
      if ! is_listening; then
        other="$(our_count)"
        echo "no_instance_on_port=$PORT"
        [ "$other" -eq 0 ] || echo "NOTE: 另有 $other 个本 profile 进程不在端口 $PORT 上，本次未处理；确认可清扫时用 '$0 close --all'"
        exit 0
      fi
      [ "$(listener_owns_ud)" = yes ] || die "端口 $PORT 的监听者不是本配置对应的 profile，拒绝关闭"
      before="$(our_count)"
      pid="$(port_owner_pid)"
      [ -n "$pid" ] || die "未找到端口 $PORT 的监听进程"
      close_by port "$pid"
    fi
    # 端口释放才是收干净的判据：Edge 浏览器进程退出会带走子进程，比逐个子进程计数可靠。
    for _ in $(seq 1 10); do is_listening || break; sleep 1; done
    left="$(our_count)"
    if is_listening; then
      die "端口 $PORT 仍被监听，实例未收回（before=$before remaining=$left）"
    fi
    echo "closed scope=$SCOPE before=$before remaining=$left port=$PORT=free"
    [ "$left" -eq 0 ] || echo "WARNING: 仍有 $left 个本 profile 进程未退出（端口已释放）"
    ;;
  tabs|open|text|eval|click|links|observe|type|press|wait)
    is_listening || die "CDP 端口 $PORT 未监听，先运行 '$0 ensure'"
    [ "$(listener_owns_ud)" = yes ] || die "端口 $PORT 的监听者不是本配置对应的 profile，拒绝驱动"
    run "$@"
    ;;
  *)
    echo "usage: $0 <status|ensure|close [--all]|tabs|open <url>|text [--max N]|eval <js>|click <sel>|links [--max N]|observe [--max N]|type <sel> (--text <s>|--text-file <f>)|press <key> [--into <sel>]|wait (--selector <css>|--url <s>|--title <s>) [--timeout ms]>" >&2
    exit 2
    ;;
esac
