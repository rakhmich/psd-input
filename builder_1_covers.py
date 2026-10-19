import re
import time
import ps_core

TEMPLATE_COVERS = ps_core.BASE_DIR / "ШАБЛОН_Обложки.psd"


def ps_filter_cover_artboards(ps_app, needed_tags: list[str]) -> str:
    """Оставляет только монтажные области из плана таблицы ('1+7') и удаляет лишние."""
    js_obj_items = ", ".join(f'"{t}": true' for t in needed_tags)
    jsx = f"""
    (function() {{
        var doc = app.activeDocument;
        var needed = {{{js_obj_items}}};
        var kept = [];
        var deleted = [];

        function getTag(name) {{
            var low = name.toLowerCase().replace(/ё/g, "е");
            var w = "";
            if (low.indexOf("1000") !== -1 || low.indexOf("1кг") !== -1) w = "1000";
            else if (low.indexOf("250") !== -1) w = "250";

            var k = "";
            if (low.indexOf("зерн") !== -1) k = "зерно";
            else if (low.indexOf("средн") !== -1 || low.indexOf("молот") !== -1) k = "молотый";

            if (w !== "" && k !== "") return w + "_" + k;
            return "";
        }}

        for (var i = doc.layerSets.length - 1; i >= 0; i--) {{
            var ab = doc.layerSets[i];
            var tag = getTag(ab.name);
            if (tag === "") continue;

            if (needed[tag]) {{
                kept.push(ab.name);
            }} else {{
                try {{
                    ab.allLocked = false;
                    doc.activeLayer = ab;
                    var delName = ab.name;
                    ab.remove();
                    deleted.push(delName);
                }} catch(e) {{
                    kept.push(ab.name + " [ОШИБКА: " + e.message + "]");
                }}
            }}
        }}
        return "ОСТАВЛЕНЫ (" + kept.length + "): [" + kept.join(", ") + "] | УДАЛЕНЫ (" + deleted.length + "): [" + deleted.join(", ") + "]";
    }})();
    """
    return ps_app.DoJavaScript(jsx)


def build_cover_for_item(ps_app, item: dict, log_fn, force_rebuild: bool = False) -> bool:
    if not TEMPLATE_COVERS.exists():
        log_fn(f"  [!] ОШИБКА: Не найден шаблон {TEMPLATE_COVERS.name}")
        return False

    lineup = item["lineup"]
    folder = item["folder"]
    if not folder:
        log_fn(f"  [!] Пропуск {lineup}: папка не найдена")
        return False

    safe_name = re.sub(r'[\\/*?:"<>|]', "_", lineup)
    out_psd = folder / f"Обложки_{safe_name}.psd"

    if out_psd.exists() and not force_rebuild:
        log_fn(f"  ├─ [Обложки] Уже существует: {out_psd.name} -> Пропуск")
        return True

    table_plan = []
    needed_tags = []
    for r in item["rows"]:
        w = r["weight"]
        k = r["kind"]
        need_str = r["need"]
        tag = f"{w}_{k}"
        if "1" in need_str and tag not in needed_tags:
            needed_tags.append(tag)
        table_plan.append((w, k, need_str))

    log_fn(f"  ├─ [📋 План из таблицы для '{lineup}']:")
    for w, k, need in table_plan:
        status_txt = f"🟢 Делаем обложку ({need})" if "1" in need else f"⚪ НЕ нужна по таблице ({need})"
        log_fn(f"  │    • Вес {w}г ({k}): {status_txt}")

    if not needed_tags:
        log_fn("  └─ [Обложки] По таблице ни одна обложка не требуется (.+7 везде) -> Пропуск")
        return False

    t0 = time.time()
    log_fn(f"  ├─ [Обложки] Создана рабочая копия '{out_psd.name}'...")
    ps_core.ps_open_copy_safely(ps_app, TEMPLATE_COVERS, out_psd)

    ab_report = ps_filter_cover_artboards(ps_app, needed_tags)
    log_fn(f"  │    • Монтажные области: {ab_report}")

    packs = item["packs"]
    for w_key, so_name in [("1000", "so_pack_1000"), ("250", "so_pack_250")]:
        is_req = any(t.startswith(w_key + "_") for t in needed_tags)
        if is_req:
            if w_key in packs:
                res = ps_core.ps_replace_so(ps_app, so_name, packs[w_key])
                log_fn(f"  │    • Смарт-объект {so_name} ({w_key}г): {res} <- '{packs[w_key].name}'")
            else:
                log_fn(f"  │    • [!] ВНИМАНИЕ: Нужна обложка {w_key}г, но файл пачки в папке не найден!")

    ps_core.ps_save_and_close_current(ps_app)
    log_fn(f"  └─ [✅ Обложки ГОТОВО за {time.time() - t0:.1f}с] -> {out_psd.name}")
    return True