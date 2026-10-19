import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import ps_core
import builder_1_covers
import builder_2_slides
import builder_3_lineup

PORT = 8765
LOG_FILE_PATH = ps_core.BASE_DIR / "last_run_log.txt"

STATE = {
    "lineups_data": [],
    "logs": [],
    "is_running": False,
    "stop_requested": False,
    "progress": 0,
    "lock": threading.Lock(),
}


def add_log(msg: str):
    with STATE["lock"]:
        STATE["logs"].append(msg)
        try:
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass
    print(msg)


def serialize_lineups(items: list[dict]) -> list[dict]:
    result = []
    for idx, it in enumerate(items):
        rel_folder = str(it["folder"].relative_to(ps_core.BASE_DIR)) if it["folder"] else "Папка не найдена"
        packs_found = sorted(list(it["packs"].keys()))
        needs = [f"{r['weight']}г {r['kind']}: {r['need']}" for r in it["rows"]]
        result.append({
            "idx": idx,
            "folder_num": it["folder_num"],
            "lineup": it["lineup"],
            "clean_title": it["clean_title"],
            "folder_rel": rel_folder,
            "has_folder": it["folder"] is not None,
            "has_packs": it["has_packs"],
            "has_taste": it["has_taste"],
            "packs_found": packs_found,
            "taste_name": it["taste_png"].name if it["taste_png"] else None,
            "needs_summary": " | ".join(needs),
            "ready": bool(it["has_packs"] and it["folder"] is not None),
        })
    return result


def reload_table_data():
    add_log("🔄 Загрузка Google Таблицы и проверка папок...")
    try:
        data = ps_core.load_all_lineups()
        STATE["lineups_data"] = data
        ready_cnt = sum(1 for x in data if x["has_packs"] and x["folder"] is not None)
        add_log(f"[OK] Загружено линеек: {len(data)}. Готовы к сборке (есть пачки .jpg): {ready_cnt} шт.")
        missing = [
            f"  • {x['folder_num']:02d}. {x['lineup']} ({x['folder'].name if x['folder'] else 'нет папки'})"
            for x in data if not (x["has_packs"] and x["folder"] is not None)
        ]
        if missing:
            add_log(f"[ℹ️] Пропущены (не найдены .jpg пачки в папке — {len(missing)} шт.):")
            for m in missing:
                add_log(m)
    except Exception as e:
        add_log(f"[!] Ошибка загрузки таблицы: {e}")


def worker_thread(selected_indices: list[int], opts: dict):
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass

    try:
        ps_app = ps_core.get_ps_app()
    except Exception as e:
        add_log(f"[ОШИБКА] Не удалось подключиться к Photoshop: {e}")
        STATE["is_running"] = False
        return

    all_items = STATE["lineups_data"]
    selected_items = [all_items[i] for i in selected_indices if 0 <= i < len(all_items)]
    if opts.get("only_first") and selected_items:
        selected_items = selected_items[:1]

    total = len(selected_items)
    force = bool(opts.get("force_rebuild"))
    do_covers = bool(opts.get("do_covers"))
    do_slides = bool(opts.get("do_slides"))
    do_lineup = bool(opts.get("do_lineup"))

    add_log("\n" + "=" * 68)
    add_log(f" 🚀 СТАРТ СБОРКИ (выбрано сортов: {total})")
    add_log("=" * 68)

    for step_idx, item in enumerate(selected_items, start=1):
        if STATE["stop_requested"]:
            add_log("\n[⏹ ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ]")
            break

        free_gb = ps_core.get_free_space_gb()
        if free_gb < ps_core.MIN_FREE_SPACE_GB:
            add_log(f"\n[🛑 ПАУЗА: МАЛО МЕСТА] На диске осталось {free_gb:.2f} ГБ! Освободите место.")
            break

        STATE["progress"] = int((step_idx - 1) / max(total, 1) * 100)
        rel_folder = item["folder"].relative_to(ps_core.BASE_DIR) if item["folder"] else "Нет папки"
        add_log(f"\n[{step_idx:02d}/{total:02d}] 📁 Папка: {rel_folder} | Сорт: {item['lineup']}")

        try:
            if do_covers:
                builder_1_covers.build_cover_for_item(ps_app, item, add_log, force_rebuild=force)
            if do_slides:
                builder_2_slides.build_slides_for_item(ps_app, item, add_log, force_rebuild=force)
            if do_lineup:
                builder_3_lineup.build_lineup_for_item(
                    ps_app, item, all_items, step_idx, add_log, force_rebuild=force
                )
        except Exception as e:
            add_log(f"  [!] ОШИБКА при сборке '{item['lineup']}': {e}")
            ps_core.ps_purge_memory(ps_app)

        STATE["progress"] = int(step_idx / max(total, 1) * 100)

    add_log("\n[✅ ЗАВЕРШЕНО] Все выбранные задачи выполнены.")
    STATE["is_running"] = False
    STATE["stop_requested"] = False


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Автосборщик PSD — Инфографика Кофе</title>
<style>
  :root {
    --bg: #121316;
    --panel: #1b1d22;
    --border: #2b2e37;
    --text: #e6e8ee;
    --muted: #8b92a5;
    --accent: #3b82f6;
    --green: #22c55e;
    --amber: #f59e0b;
    --red: #ef4444;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--text);
    height: 100vh; display: flex; flex-direction: column; overflow: hidden;
  }
  header {
    background: var(--panel); border-bottom: 1px solid var(--border);
    padding: 12px 20px; display: flex; align-items: center; justify-content: space-between; gap: 16px;
  }
  .tpl-checks { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  .tpl-checks label {
    display: flex; align-items: center; gap: 7px; cursor: pointer;
    font-size: 13.5px; background: #23262d; padding: 6px 12px; border-radius: 6px;
    border: 1px solid var(--border); user-select: none;
  }
  .disk-badge {
    font-weight: 700; font-size: 13.5px; color: #34d399;
    background: rgba(52, 211, 153, 0.1); padding: 6px 12px; border-radius: 6px;
    border: 1px solid rgba(52, 211, 153, 0.25); white-space: nowrap;
  }
  main {
    flex: 1; display: grid; grid-template-columns: 480px 1fr; gap: 12px;
    padding: 12px 16px; overflow: hidden;
  }
  .col {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    display: flex; flex-direction: column; overflow: hidden;
  }
  .col-header {
    padding: 10px 12px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;
  }
  .btn-group { display: flex; gap: 6px; flex-wrap: wrap; }
  button {
    background: #2b2f3a; color: var(--text); border: 1px solid #3a3f4d;
    padding: 6px 11px; border-radius: 6px; cursor: pointer; font-size: 12.5px; font-weight: 600;
    transition: 0.15s;
  }
  button:hover:not(:disabled) { filter: brightness(1.15); }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  .btn-primary { background: #2563eb; border-color: #3b82f6; color: #fff; }
  .btn-success { background: #16a34a; border-color: #22c55e; color: #fff; }
  .btn-danger  { background: #dc2626; border-color: #ef4444; color: #fff; }
  .search-box {
    width: 100%; padding: 7px 10px; background: #121316; border: 1px solid var(--border);
    color: var(--text); border-radius: 6px; font-size: 13px; margin-top: 6px;
  }
  .list-wrap { flex: 1; overflow-y: auto; padding: 8px; }
  .item-row {
    display: flex; align-items: flex-start; gap: 9px; padding: 8px 10px;
    border-radius: 6px; border: 1px solid transparent; cursor: pointer; margin-bottom: 4px;
  }
  .item-row:hover { background: #23262e; border-color: var(--border); }
  .item-row.missing { opacity: 0.55; }
  .item-row input { margin-top: 3px; transform: scale(1.15); cursor: pointer; }
  .item-body { flex: 1; min-width: 0; }
  .item-title { font-size: 13.5px; font-weight: 600; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .item-sub { font-size: 11.5px; color: var(--muted); margin-top: 2px; word-break: break-all; }
  .badge {
    font-size: 10.5px; padding: 1px 6px; border-radius: 4px; font-weight: 600;
  }
  .b-ok { background: rgba(34,197,94,0.15); color: #4ade80; }
  .b-warn { background: rgba(245,158,11,0.15); color: #fbbf24; }
  .b-err { background: rgba(239,68,68,0.15); color: #f87171; }
  #logBox {
    flex: 1; margin: 0; padding: 12px; overflow-y: auto;
    background: #0d0e11; color: #d1d5db; font-family: Consolas, monospace;
    font-size: 12.5px; line-height: 1.5; white-space: pre-wrap; user-select: text;
  }
  footer {
    background: var(--panel); border-top: 1px solid var(--border);
    padding: 10px 20px; display: flex; flex-direction: column; gap: 8px;
  }
  .progress-bar {
    width: 100%; height: 8px; background: #121316; border-radius: 4px; overflow: hidden;
    border: 1px solid var(--border);
  }
  .progress-fill {
    height: 100%; width: 0%; background: linear-gradient(90deg, #3b82f6, #22c55e);
    transition: width 0.25s;
  }
  .footer-controls { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .toast {
    position: fixed; bottom: 75px; right: 24px; background: #22c55e; color: #000;
    font-weight: 700; padding: 8px 14px; border-radius: 6px; display: none;
  }
</style>
</head>
<body>

<header>
  <div class="tpl-checks">
    <strong style="font-size:14px;">Какие PSD собираем:</strong>
    <label><input type="checkbox" id="chkCovers" checked> 1. ШАБЛОН_Обложки.psd</label>
    <label><input type="checkbox" id="chkSlides" checked> 2. ШАБЛОН_Слайды.psd (Вкус / Происхождение / Финал)</label>
    <label><input type="checkbox" id="chkLineup"> 3. ШАБЛОН_Линейка.psd</label>
    <label style="border-color:#f59e0b55; color:#fcd34d;">
      <input type="checkbox" id="chkForce" checked> Перезаписывать уже готовые PSD
    </label>
  </div>
  <div class="disk-badge" id="diskBadge">Свободно: -- ГБ</div>
</header>

<main>
  <!-- Левая колонка: список сортов -->
  <div class="col">
    <div class="col-header">
      <div class="btn-group">
        <button onclick="selectReady()">✅ Выбрать готовые</button>
        <button onclick="selectAll(false)">Снять все</button>
        <button onclick="reloadTable()">🔄 Обновить таблицу</button>
      </div>
      <span id="countInfo" style="font-size:12px; color:var(--muted);">0 / 0</span>
      <input type="text" id="searchInput" class="search-box" placeholder="🔍 Быстрый фильтр по названию или номеру папки..." oninput="renderList()">
    </div>
    <div class="list-wrap" id="lineupsList"></div>
  </div>

  <!-- Правая колонка: живой лог -->
  <div class="col">
    <div class="col-header">
      <strong style="font-size:13.5px;">Живой лог выполнения (выделяется мышкой и Ctrl+C):</strong>
      <div class="btn-group">
        <button class="btn-primary" onclick="copyFullLog()">📋 Скопировать весь лог</button>
        <button onclick="clearLogView()">Очистить окно</button>
      </div>
    </div>
    <pre id="logBox"></pre>
  </div>
</main>

<footer>
  <div class="progress-bar"><div class="progress-fill" id="progFill"></div></div>
  <div class="footer-controls">
    <div class="btn-group">
      <button id="btnTest" class="btn-primary" style="padding:9px 16px; font-size:13.5px;" onclick="startRun(true)">
        🧪 ТЕСТ (только 1-й выбранный сорт)
      </button>
      <button id="btnRunAll" class="btn-success" style="padding:9px 16px; font-size:13.5px;" onclick="startRun(false)">
        🚀 ЗАПУСТИТЬ ВСЕ ВЫБРАННЫЕ
      </button>
      <button id="btnStop" class="btn-danger" style="padding:9px 16px; font-size:13.5px;" onclick="stopRun()" disabled>
        ⏹ СТОП (после текущего PSD)
      </button>
    </div>
    <button onclick="purgeCache()">🧹 Очистить историю ФШ (без сброса буфера обмена)</button>
  </div>
</footer>

<div class="toast" id="toast">Скопировано в буфер обмена!</div>

<script>
let lineups = [];
let selectedSet = new Set();
let lastLogLen = 0;

async function fetchData() {
  const res = await fetch('/api/data');
  const data = await res.json();
  lineups = data.items || [];
  selectedSet.clear();
  lineups.forEach(it => { if (it.ready) selectedSet.add(it.idx); });
  renderList();
}

function renderList() {
  const q = document.getElementById('searchInput').value.trim().toLowerCase();
  const wrap = document.getElementById('lineupsList');
  wrap.innerHTML = '';

  lineups.forEach(it => {
    const prefix = it.folder_num < 99 ? String(it.folder_num).padStart(2, '0') + '.' : '??.';
    const fullText = `${prefix} ${it.lineup} ${it.folder_rel}`.toLowerCase();
    if (q && !fullText.includes(q)) return;

    const row = document.createElement('label');
    row.className = 'item-row' + (it.ready ? '' : ' missing');

    const chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.checked = selectedSet.has(it.idx);
    chk.onchange = () => {
      if (chk.checked) selectedSet.add(it.idx);
      else selectedSet.delete(it.idx);
      updateCounter();
    };

    let badges = '';
    if (it.has_packs) {
      badges += `<span class="badge b-ok">Пачки: ${it.packs_found.join(', ')}г</span>`;
    } else {
      badges += `<span class="badge b-err">Нет пачки .jpg</span>`;
    }
    if (it.has_taste) {
      badges += `<span class="badge b-ok">Вкус PNG</span>`;
    } else {
      badges += `<span class="badge b-warn">Нет вкуса .png</span>`;
    }

    const body = document.createElement('div');
    body.className = 'item-body';
    body.innerHTML = `
      <div class="item-title"><span>${prefix} ${it.lineup}</span> ${badges}</div>
      <div class="item-sub">📁 ${it.folder_rel} | ${it.needs_summary}</div>
    `;

    row.appendChild(chk);
    row.appendChild(body);
    wrap.appendChild(row);
  });
  updateCounter();
}

function updateCounter() {
  document.getElementById('countInfo').textContent = `Выбрано: ${selectedSet.size} из ${lineups.length}`;
}

function selectReady() {
  selectedSet.clear();
  lineups.forEach(it => { if (it.ready) selectedSet.add(it.idx); });
  renderList();
}

function selectAll(flag) {
  selectedSet.clear();
  if (flag) lineups.forEach(it => selectedSet.add(it.idx));
  renderList();
}

async function reloadTable() {
  await fetch('/api/reload', { method: 'POST' });
  await fetchData();
}

async function startRun(onlyFirst) {
  const indices = Array.from(selectedSet).sort((a, b) => a - b);
  if (indices.length === 0) {
    alert('Отметьте галочками хотя бы один сорт слева!');
    return;
  }
  await fetch('/api/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      indices,
      only_first: onlyFirst,
      do_covers: document.getElementById('chkCovers').checked,
      do_slides: document.getElementById('chkSlides').checked,
      do_lineup: document.getElementById('chkLineup').checked,
      force_rebuild: document.getElementById('chkForce').checked
    })
  });
}

async function stopRun() {
  await fetch('/api/stop', { method: 'POST' });
}

async function purgeCache() {
  await fetch('/api/purge', { method: 'POST' });
}

function copyFullLog() {
  const text = document.getElementById('logBox').innerText;
  navigator.clipboard.writeText(text).then(() => {
    const t = document.getElementById('toast');
    t.style.display = 'block';
    setTimeout(() => t.style.display = 'none', 2000);
  });
}

function clearLogView() {
  document.getElementById('logBox').textContent = '';
}

async function pollStatus() {
  try {
    const res = await fetch('/api/status');
    const st = await res.json();
    document.getElementById('diskBadge').textContent = `Свободно: ${st.disk_gb.toFixed(1)} ГБ`;
    document.getElementById('progFill').style.width = `${st.progress}%`;

    document.getElementById('btnTest').disabled = st.is_running;
    document.getElementById('btnRunAll').disabled = st.is_running;
    document.getElementById('btnStop').disabled = !st.is_running;

    if (st.logs.length !== lastLogLen) {
      const logBox = document.getElementById('logBox');
      const isAtBottom = (logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight) < 60;
      logBox.textContent = st.logs.join('\n');
      lastLogLen = st.logs.length;
      if (isAtBottom) logBox.scrollTop = logBox.scrollHeight;
    }
  } catch (e) {}
  setTimeout(pollStatus, 500);
}

fetchData();
pollStatus();
</script>
</body>
</html>
"""


class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Не засоряем консоль HTTP-запросами

    def _send_json(self, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/data":
            self._send_json({"items": serialize_lineups(STATE["lineups_data"])})
        elif path == "/api/status":
            with STATE["lock"]:
                logs_copy = list(STATE["logs"])
            self._send_json({
                "is_running": STATE["is_running"],
                "progress": STATE["progress"],
                "disk_gb": ps_core.get_free_space_gb(),
                "logs": logs_copy,
            })
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"

        if path == "/api/reload":
            reload_table_data()
            self._send_json({"ok": True})

        elif path == "/api/start":
            if not STATE["is_running"]:
                opts = json.loads(raw_body)
                indices = opts.get("indices", [])
                STATE["is_running"] = True
                STATE["stop_requested"] = False
                STATE["progress"] = 0
                threading.Thread(target=worker_thread, args=(indices, opts), daemon=True).start()
            self._send_json({"ok": True})

        elif path == "/api/stop":
            if STATE["is_running"]:
                STATE["stop_requested"] = True
                add_log("\n[⏳ СТОП ЗАПРОШЕН] Дожидаемся сохранения текущего PSD и останавливаемся...")
            self._send_json({"ok": True})

        elif path == "/api/purge":
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass
            try:
                ps = ps_core.get_ps_app()
                ps_core.ps_purge_memory(ps)
                add_log("[🧹 КЭШ] История Photoshop очищена (системный буфер обмена сохранён)!")
            except Exception as e:
                add_log(f"[!] Не удалось очистить кэш ФШ: {e}")
            self._send_json({"ok": True})
        else:
            self.send_error(404)


def main():
    try:
        LOG_FILE_PATH.write_text("", encoding="utf-8")
    except Exception:
        pass

    reload_table_data()
    url = f"http://127.0.0.1:{PORT}"
    server = ThreadingHTTPServer(("127.0.0.1", PORT), WebHandler)
    print(f"\n=======================================================")
    print(f" 🌐 Веб-панель запущена: {url}")
    print(f" (Не закрывайте это черное окно во время работы)")
    print(f"=======================================================\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()