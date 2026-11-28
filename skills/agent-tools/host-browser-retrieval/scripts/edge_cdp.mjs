#!/usr/bin/env node
// edge_cdp.mjs — Windows 侧 CDP 客户端（零依赖，Node >= 21）。
// 由 WSL 侧 host_browser.sh 通过 PowerShell interop 调用，控制宿主机 Edge 的独立调试实例。
// 只连本机回环端口，不做启动/关闭动作（生命周期由 host_browser.sh 负责）。
//
// 参数经 stdin 传入（--stdin-args + JSON 数组）：PowerShell 5.1 向原生命令传参时会剥掉
// 双引号，含引号的 JS 表达式会被静默改写，故不走命令行参数通道。
import { readFileSync } from 'node:fs'

// --flag=value 与 --flag value 等价：只认空格分隔会让 `--max=50` 被静默忽略、退回默认值。
const splitFlags = list => list.flatMap(a => {
  if (typeof a !== 'string' || !a.startsWith('--')) return [a]
  const i = a.indexOf('=')
  return i > 2 ? [a.slice(0, i), a.slice(i + 1)] : [a]
})

const argvRaw = splitFlags(process.argv.slice(2))
let args
if (argvRaw.includes('--stdin-args')) {
  try {
    args = splitFlags(JSON.parse(readFileSync(0, 'utf8')))
  } catch (e) {
    console.error(`ERROR: 无法从 stdin 解析参数 JSON: ${e.message}`)
    process.exit(2)
  }
} else {
  args = argvRaw
}

const cmd = args[0]
// --port 由包装器放在命令行；stdin 模式下两个来源都要看，否则端口被静默忽略而打到默认实例。
const flagSource = argvRaw.concat(args)
const numFlag = (name, def) => {
  const i = flagSource.indexOf(name)
  if (i === -1) return def
  const v = Number(flagSource[i + 1])
  if (!Number.isInteger(v) || v <= 0) {
    throw new Error(`${name} 需要正整数，收到 ${JSON.stringify(flagSource[i + 1])}`)
  }
  return v
}
const PORT = numFlag('--port', Number(process.env.EDGE_CDP_PORT || 9222))
const HOST = process.env.EDGE_CDP_HOST || '127.0.0.1'

async function targets() {
  const r = await fetch(`http://${HOST}:${PORT}/json/list`)
  if (!r.ok) throw new Error(`/json/list HTTP ${r.status}`)
  return (await r.json()).filter(t => t.type === 'page')
}

async function pick() {
  const pages = await targets()
  // 放行 http(s) 与 edge:// 内部页（收藏夹/设置/历史等本就是合法操作目标）。
  // 不放行 chrome-error://、devtools://、chrome-extension:// 等调试/错误态页面。
  const usable = pages.find(t => /^https?:/.test(t.url) || /^edge:/.test(t.url))
  if (usable) return usable
  const blank = pages.find(t => t.url === 'about:blank')
  if (blank) return blank
  const seen = pages.map(t => t.url).join(', ') || '<无 page target>'
  throw new Error(`没有可用的 http(s)/edge:// 标签页（当前: ${seen}）；先运行 open <url>`)
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl)
    const pending = new Map()
    const events = []
    let id = 0
    ws.addEventListener('message', ev => {
      const m = JSON.parse(ev.data)
      if (m.id != null && pending.has(m.id)) {
        const p = pending.get(m.id)
        pending.delete(m.id)
        m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result)
      } else if (m.method) {
        events.push(m.method)
      }
    })
    ws.addEventListener('error', () => reject(new Error('WebSocket error')), { once: true })
    ws.addEventListener('open', () => resolve({
      events,
      send: (method, params = {}) => new Promise((res, rej) => {
        const n = ++id
        pending.set(n, { resolve: res, reject: rej })
        ws.send(JSON.stringify({ id: n, method, params }))
      }),
      close: () => ws.close(),
    }))
  })
}

// 页面求值异常一律抛出：静默返回错误字符串会让调用方把异常当数据。
async function evalJson(cdp, expression) {
  const r = await cdp.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
  const d = r.exceptionDetails
  if (d) {
    const detail = d.exception?.description ? ` — ${String(d.exception.description).split('\n')[0]}` : ''
    throw new Error(`页面求值异常: ${d.text}${detail}`)
  }
  return r.result.value
}

// 就地隐藏噪音节点后取 innerText：innerText 需要布局，脱离文档的克隆节点会退化成 textContent。
// 候选选择：main 系元素须达到 body 文本量的 40% 才采用，否则用 body —— 直接取
// 'main,article,[role=main]' 的第一个匹配会命中正文之前的促销/相关卡片。
const READABLE = `(() => {
  const sel = 'script,style,noscript,svg,iframe,nav,header,footer,aside,form,[role=navigation],[aria-hidden=true]'
  const hidden = []
  document.querySelectorAll(sel).forEach(n => { hidden.push([n, n.style.display]); n.style.display = 'none' })
  try {
    const body = document.body
    const bodyLen = (body.innerText || '').length
    let root = body
    for (const el of document.querySelectorAll('main,[role=main],#main,#content')) {
      if ((el.innerText || '').length >= bodyLen * 0.4) { root = el; break }
    }
    return (root.innerText || root.textContent || '').replace(/[ \\t]+\\n/g, '\\n').replace(/\\n{3,}/g, '\\n\\n').trim()
  } finally {
    hidden.forEach(([n, d]) => { n.style.display = d })
  }
})()`

// 截断不得切裂代理对，否则尾部会出现 U+FFFD，影响逐字引用。
const clip = (txt, max) => {
  if (txt.length <= max) return txt
  let cut = txt.slice(0, max)
  if (/[\uD800-\uDBFF]$/.test(cut)) cut = cut.slice(0, -1)
  return `${cut}\n...[truncated ${txt.length - max} chars of ${txt.length}]`
}

async function main() {
  if (cmd === 'tabs') {
    console.log(JSON.stringify((await targets()).map(t => ({ title: t.title, url: t.url })), null, 2))
    return
  }
  if (!cmd) throw new Error('缺少子命令')
  const t = await pick()
  const cdp = await connect(t.webSocketDebuggerUrl)
  try {
    await cdp.send('Page.enable')
    if (cmd === 'open') {
      const url = args[1]
      if (!url) throw new Error('open 需要 URL')
      await cdp.send('Page.navigate', { url })
      const deadline = Date.now() + 30000
      while (!cdp.events.includes('Page.loadEventFired') && Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 150))
      }
      await new Promise(r => setTimeout(r, 800))
      console.log(await evalJson(cdp, 'JSON.stringify({title:document.title,url:location.href})'))
    } else if (cmd === 'text') {
      console.log(clip((await evalJson(cdp, READABLE)) || '', numFlag('--max', 8000)))
    } else if (cmd === 'eval') {
      const expr = args[1]
      if (!expr) throw new Error('eval 需要表达式')
      console.log(JSON.stringify(await evalJson(cdp, expr)))
    } else if (cmd === 'click') {
      const sel = args[1]
      if (!sel) throw new Error('click 需要选择器')
      console.log(await evalJson(cdp, `(() => {
        const e = document.querySelector(${JSON.stringify(sel)})
        if (!e) return 'NOT_FOUND'
        e.scrollIntoView({ block: 'center' })
        e.click()
        return 'CLICKED: ' + ((e.innerText || e.value || '').trim().slice(0, 80))
      })()`))
    } else if (cmd === 'links') {
      const max = numFlag('--max', 60)
      console.log(await evalJson(cdp, `JSON.stringify([...document.querySelectorAll('a[href]')]
        .slice(0, ${max})
        .map(a => ({ text: (a.innerText || '').trim().slice(0, 80), href: a.href })))`))
    } else if (cmd === 'observe') {
      // 压缩可交互元素表供自动化决策喂入：id/role/label/interactive。
      // 只收集可见且可交互的节点；label 优先 aria-label > placeholder > innerText > value > title。
      // --max 默认 100。
      const max = numFlag('--max', 100)
      console.log(await evalJson(cdp, `JSON.stringify((() => {
        const seen = new Set()
        const out = []
        const labelOf = e => (e.getAttribute('aria-label') || e.placeholder || (e.innerText || e.value || e.title || '')).toString().trim().replace(/\\s+/g, ' ').slice(0, 120)
        const roleOf = e => {
          const tag = e.tagName.toLowerCase()
          if (e.getAttribute('role')) return e.getAttribute('role')
          if (tag === 'a') return 'link'
          if (tag === 'button') return 'button'
          if (tag === 'input') return {submit:'button',button:'button',checkbox:'checkbox',radio:'radio'}[e.type] || 'textbox'
          if (tag === 'textarea') return 'textbox'
          if (tag === 'select') return 'combobox'
          return tag
        }
        const interactive = e => {
          const tag = e.tagName.toLowerCase()
          if (e.disabled || e.readOnly) return false
          const r = e.getBoundingClientRect()
          return r.width > 0 && r.height > 0
        }
        const sels = 'a[href],button,input,textarea,select,[role=button],[role=link],[role=textbox],[role=combobox],[role=checkbox],[role=radio],[contenteditable=true],[onclick]'
        let i = 0
        for (const e of document.querySelectorAll(sels)) {
          if (out.length >= ${max}) break
          let label = labelOf(e)
          // 输入框/文本域没 label 也要收：用 id/name/placeholder/tag 兜底，否则自动化决策看不到搜索框。
          if (!label) label = e.id || e.name || e.getAttribute('name') || e.tagName.toLowerCase()
          const key = e.tagName + '|' + label + '|' + (e.getAttribute('href') || '')
          if (seen.has(key)) continue
          seen.add(key)
          // 给元素一个稳定 id 供 click/type 后续使用
          if (!e.id) e.id = 'hbr-' + i
          out.push({ id: e.id, role: roleOf(e), label, interactive: interactive(e) })
          i++
        }
        return out
      })())`))
    } else if (cmd === 'type') {
      // 用法: type <selector> --text-file <path> | --text <literal>
      // 文本走 stdin JSON（host_browser.sh 的 --text-file 路径）或 --text；不经 shell 命令行拼接。
      const sel = args[1]
      if (!sel) throw new Error('type 需要选择器')
      const ti = args.indexOf('--text')
      const fi = args.indexOf('--text-file')
      if (ti === -1 && fi === -1) throw new Error('type 需要 --text <literal> 或 --text-file <path>')
      let text
      if (fi !== -1) {
        const { readFileSync } = await import('node:fs')
        text = readFileSync(args[fi + 1], 'utf8')
      } else {
        text = args[ti + 1] || ''
      }
      console.log(await evalJson(cdp, `(() => {
        const e = document.querySelector(${JSON.stringify(sel)})
        if (!e) return 'NOT_FOUND'
        e.scrollIntoView({ block: 'center' })
        e.focus()
        e.value = ${JSON.stringify(text)}
        e.dispatchEvent(new Event('input', { bubbles: true }))
        e.dispatchEvent(new Event('change', { bubbles: true }))
        return JSON.stringify({ typed: e.value.slice(0, 80), focused: document.activeElement === e })
      })()`))
    } else if (cmd === 'press') {
      // 白名单键 + 可选 selector 焦点目标；不开放任意键盘序列（防注入与语义漂移）。
      const key = (args[1] || '').toLowerCase()
      const KEYS = { enter: 'Enter', return: 'Enter', tab: 'Tab', escape: 'Escape', esc: 'Escape',
                     backspace: 'Backspace', delete: 'Delete', space: ' ', home: 'Home', end: 'End',
                     arrowup: 'ArrowUp', arrowdown: 'ArrowDown', arrowleft: 'ArrowLeft', arrowright: 'ArrowRight' }
      const k = KEYS[key]
      if (!k) throw new Error(`press 需要白名单键: ${Object.keys(KEYS).join('|')}`)
      const selIdx = args.indexOf('--into')
      const sel = selIdx !== -1 ? args[selIdx + 1] : ''
      console.log(await evalJson(cdp, `(() => {
        const target = ${JSON.stringify(sel)} ? document.querySelector(${JSON.stringify(sel)}) : document.activeElement
        if (!target) return 'NO_TARGET'
        target.focus()
        for (const type of ['keydown', 'keypress', 'keyup']) {
          target.dispatchEvent(new KeyboardEvent(type, { key: ${JSON.stringify(k)}, bubbles: true }))
        }
        return JSON.stringify({ pressed: ${JSON.stringify(k)}, into: ${JSON.stringify(sel)} || 'activeElement', active: document.activeElement.tagName })
      })()`))
    } else if (cmd === 'wait') {
      // 等待条件成立。--selector <css> | --url <substr> | --title <substr> 三选一；--timeout ms（默认 15000）。
      const timeout = numFlag('--timeout', 15000)
      const selIdx = args.indexOf('--selector')
      const urlIdx = args.indexOf('--url')
      const titleIdx = args.indexOf('--title')
      const modes = [selIdx !== -1, urlIdx !== -1, titleIdx !== -1].filter(Boolean).length
      if (modes !== 1) throw new Error('wait 需要且仅需要 --selector <css> / --url <substr> / --title <substr> 之一')
      const check = selIdx !== -1
        ? `!!document.querySelector(${JSON.stringify(args[selIdx + 1])})`
        : urlIdx !== -1
          ? `location.href.includes(${JSON.stringify(args[urlIdx + 1])})`
          : `document.title.includes(${JSON.stringify(args[titleIdx + 1])})`
      const deadline = Date.now() + timeout
      let ok = false
      while (Date.now() < deadline) {
        ok = await evalJson(cdp, check)
        if (ok) break
        await new Promise(r => setTimeout(r, 300))
      }
      console.log(JSON.stringify({ ok, timeout_ms: timeout }))
      if (!ok) process.exitCode = 4
    } else {
      console.error('usage: edge_cdp.mjs --stdin-args --port N <tabs|open <url>|text [--max N]|eval <js>|click <sel>|links [--max N]|observe [--max N]|type <sel> (--text <s>|--text-file <f>)|press <key> [--into <sel>]|wait (--selector <css>|--url <s>|--title <s>) [--timeout ms]>')
      process.exitCode = 2
    }
  } finally {
    cdp.close()
  }
}

main().catch(e => { console.error(`ERROR: ${e.message}`); process.exitCode = 1 })
