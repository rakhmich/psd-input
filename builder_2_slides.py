import re
import time
import ps_core

TEMPLATE_SLIDES = ps_core.BASE_DIR / "ШАБЛОН_Слайды.psd"


def ps_set_scale_beans(ps_app, group_names: list[str], score_raw: str) -> str:
    digits = re.findall(r"\d+", score_raw)
    score = int(digits[0]) if digits else 3
    names_js = "[" + ", ".join(f'"{n.lower()}"' for n in group_names) + "]"

    jsx = f"""
    (function() {{
        var doc = app.activeDocument;
        var targetNames = {names_js};

        function findGroup(parent) {{
            for (var i = 0; i < parent.layers.length; i++) {{
                var lyr = parent.layers[i];
                if (lyr.typename === "LayerSet") {{
                    var low = lyr.name.toLowerCase();
                    for (var k = 0; k < targetNames.length; k++) {{
                        if (low === targetNames[k]) return lyr;
                    }}
                    var sub = findGroup(lyr);
                    if (sub) return sub;
                }}
            }}
            return null;
        }}

        var scaleGrp = findGroup(doc);
        if (!scaleGrp) return "GROUP_NOT_FOUND";

        var changed = 0;
        function toggleNumbers(parent) {{
            for (var i = 0; i < parent.layers.length; i++) {{
                var lyr = parent.layers[i];
                if (lyr.typename === "LayerSet") {{
                    var n = parseInt(lyr.name, 10);
                    if (!isNaN(n) && n >= 1 && n <= 5) {{
                        for (var j = 0; j < lyr.layers.length; j++) {{
                            var child = lyr.layers[j];
                            if (child.name === "+") {{
                                child.visible = (n <= {score});
                                changed++;
                            }}
                        }}
                    }} else {{
                        toggleNumbers(lyr);
                    }}
                }}
            }}
        }}
        toggleNumbers(scaleGrp);
        return "OK(" + scaleGrp.name + "=" + {score} + ")";
    }})();
    """
    return ps_app.DoJavaScript(jsx)


def ps_set_taste_slot(ps_app, idx: int, text_val: str | None) -> str:
    """
    Если вкус есть: включает группу grp_taste_{idx}, текстовый слой И все слои плашки внутри группы!
    Если вкуса нет (например, всего 2 или 3 вкуса): скрывает группу и текст лишнего слота.
    """
    grp_name = f"grp_taste_{idx}"
    txt_name = f"txt_taste_{idx}"

    if not text_val:
        res_g = ps_core.ps_set_visibility(ps_app, grp_name, False)
        res_t = ps_core.ps_set_visibility(ps_app, txt_name, False)
        return f"СКРЫТ ({res_g}/{res_t})"

    safe_txt = text_val.replace("\\", "\\\\").replace('"', '\\"')
    jsx = f"""
    (function() {{
        var doc = app.activeDocument;
        var grpName = "{grp_name}";
        var txtName = "{txt_name}";
        var foundGrp = null;
        var foundTxt = null;

        function walk(parent) {{
            for (var i = 0; i < parent.layers.length; i++) {{
                var lyr = parent.layers[i];
                var clean = lyr.name.replace(/^\\s+|\\s+$/g, "").toLowerCase();
                if (lyr.typename === "LayerSet" && (clean === grpName || clean.indexOf(grpName + " ") === 0)) {{
                    foundGrp = lyr;
                }}
                if (lyr.kind == LayerKind.TEXT && (clean === txtName || clean.indexOf(txtName + " ") === 0)) {{
                    foundTxt = lyr;
                }}
                if (lyr.typename === "LayerSet") walk(lyr);
            }}
        }}
        walk(doc);

        // Если группа не найдена по имени, но найден текстовый слой и он лежит в своей подгруппе плашки
        if (!foundGrp && foundTxt && foundTxt.parent && foundTxt.parent.typename === "LayerSet") {{
            var p = foundTxt.parent;
            var txtCount = 0;
            for (var m = 0; m < p.layers.length; m++) {{
                if (p.layers[m].kind == LayerKind.TEXT) txtCount++;
            }}
            if (txtCount === 1) foundGrp = p;
        }}

        if (foundGrp) {{
            foundGrp.visible = true;
            // Принудительно включаем ВСЕ слои внутри группы (и текст, и цветную плашку!)
            for (var j = 0; j < foundGrp.layers.length; j++) {{
                foundGrp.layers[j].visible = true;
                if (!foundTxt && foundGrp.layers[j].kind == LayerKind.TEXT) {{
                    foundTxt = foundGrp.layers[j];
                }}
            }}
        }}

        if (foundTxt) {{
            foundTxt.visible = true;
            foundTxt.textItem.contents = "{safe_txt}";
            return "OK";
        }}
        return "NOT_FOUND";
    }})();
    """
    res = ps_app.DoJavaScript(jsx)
    return f"{res} -> '{text_val}'"


def ps_set_qscore_and_word(ps_app, q_num: str, q_word: str) -> str:
    """
    Вписывает 'Q <число>' в txt_qscore (в одну строку без переноса!)
    и слово 'БАЛЛ/БАЛЛА/БАЛЛОВ' в отдельный слой 'txt_q-баллы'.
    """
    res_num = ps_core.ps_set_text(ps_app, "txt_qscore", f"Q {q_num}")

    # Ищем слой 'txt_q-баллы' с сохранением регистра (БАЛЛА или балла)
    jsx_word = f"""
    (function() {{
        var doc = app.activeDocument;
        var matches = [];
        function walk(parent) {{
            for (var i = 0; i < parent.layers.length; i++) {{
                var lyr = parent.layers[i];
                if (lyr.kind == LayerKind.TEXT) {{
                    var low = lyr.name.replace(/^\\s+|\\s+$/g, "").toLowerCase().replace(/ё/g, "е");
                    if (low === "txt_q-баллы" || low.indexOf("txt_q-балл") === 0 || low === "txt_q_баллы") {{
                        matches.push(lyr);
                    }}
                }}
                if (lyr.typename === "LayerSet") walk(lyr);
            }}
        }}
        walk(doc);
        if (matches.length === 0) return "NOT_FOUND";
        for (var k = 0; k < matches.length; k++) {{
            var oldTxt = matches[k].textItem.contents;
            var newWord = "{q_word}";
            if (oldTxt && oldTxt === oldTxt.toLowerCase()) {{
                newWord = newWord.toLowerCase();
            }}
            matches[k].textItem.contents = newWord;
        }}
        return "OK";
    }})();
    """
    res_word = ps_app.DoJavaScript(jsx_word)
    return f"Число={res_num} ('Q {q_num}'), Слово={res_word} ('{q_word}')"


def ps_set_or_hide_height(ps_app, height_val: str | None) -> str:
    """Если высоты нет — скрывает txt_height (и его группу, если есть). Если есть — вписывает."""
    if not height_val:
        r_g = ps_core.ps_set_visibility(ps_app, "grp_height", False)
        r_t = ps_core.ps_set_visibility(ps_app, "txt_height", False)
        return f"СКРЫТА (нет в таблице, {r_g}/{r_t})"

    ps_core.ps_set_visibility(ps_app, "grp_height", True)
    ps_core.ps_set_visibility(ps_app, "txt_height", True)

    safe_h = height_val.replace("\\", "\\\\").replace('"', '\\"')
    jsx_h = f"""
    (function() {{
        var doc = app.activeDocument;
        var matches = [];
        function walk(parent) {{
            for (var i = 0; i < parent.layers.length; i++) {{
                var lyr = parent.layers[i];
                if (lyr.kind == LayerKind.TEXT) {{
                    var low = lyr.name.replace(/^\\s+|\\s+$/g, "").toLowerCase();
                    if (low === "txt_height" || low.indexOf("txt_height ") === 0) {{
                        matches.push(lyr);
                    }}
                }}
                if (lyr.typename === "LayerSet") walk(lyr);
            }}
        }}
        walk(doc);
        if (matches.length === 0) return "NOT_FOUND";
        for (var k = 0; k < matches.length; k++) {{
            var oldTxt = matches[k].textItem.contents || "";
            if (oldTxt.toUpperCase().indexOf("ВЫСОТА") !== -1) {{
                matches[k].textItem.contents = "ВЫСОТА: {safe_h}";
            }} else {{
                matches[k].textItem.contents = "{safe_h}";
            }}
        }}
        return "OK";
    }})();
    """
    res = ps_app.DoJavaScript(jsx_h)
    return f"{res} ('{height_val}')"


def build_slides_for_item(ps_app, item: dict, log_fn, force_rebuild: bool = False) -> bool:
    if not TEMPLATE_SLIDES.exists():
        log_fn(f"  [!] ОШИБКА: Не найден шаблон {TEMPLATE_SLIDES.name}")
        return False

    lineup = item["lineup"]
    folder = item["folder"]
    if not folder:
        log_fn(f"  [!] Пропуск {lineup}: папка не найдена")
        return False

    safe_name = re.sub(r'[\\/*?:"<>|]', "_", lineup)
    out_psd = folder / f"Слайды_{safe_name}.psd"

    if out_psd.exists() and not force_rebuild:
        log_fn(f"  ├─ [Слайды] Уже существует: {out_psd.name} -> Пропуск")
        return True

    t0 = time.time()
    log_fn(f"  ├─ [Слайды] Создана рабочая копия '{out_psd.name}'...")
    ps_core.ps_open_copy_safely(ps_app, TEMPLATE_SLIDES, out_psd)

    # 1. СЛАЙД БУКЕТ ВКУСА
    if item["taste_png"]:
        res_taste_so = ps_core.ps_replace_so(ps_app, "so_taste", item["taste_png"])
        log_fn(f"  │    • Букет вкуса (so_taste): {res_taste_so} ({item['taste_png'].name})")
    else:
        log_fn("  │    • [!] ВНИМАНИЕ: Файл вкуса *-Photoroom.png не найден!")

    tastes = ps_core.parse_tastes(item["taste_raw"])
    for idx in range(1, 5):
        t_val = tastes[idx - 1] if idx <= len(tastes) else None
        st = ps_set_taste_slot(ps_app, idx, t_val)
        log_fn(f"  │    • Вкус #{idx}: {st}")

    # Q-Баллы: отдельно число в txt_qscore и отдельно слово в txt_q-баллы
    q_num, q_word = ps_core.format_q_score(item["qscore"])
    res_q = ps_set_qscore_and_word(ps_app, q_num, q_word)
    log_fn(f"  │    • Q-Баллы: {res_q}")

    # Шкалы 1..5
    r_acid = ps_set_scale_beans(ps_app, ["кислотноть", "кислотность"], item["acidity"])
    r_str  = ps_set_scale_beans(ps_app, ["крепость"], item["strength"])
    r_rst  = ps_set_scale_beans(ps_app, ["обжарка"], item["roast"])
    log_fn(f"  │    • Шкалы: {r_acid} | {r_str} | {r_rst}")

    # 2. СЛАЙД ПРОИСХОЖДЕНИЕ
    countries_slash = re.sub(r"\s*,\s*", " / ", item["country"].strip()) if item["country"] else "Бразилия"
    res_cnt = ps_core.ps_set_text(ps_app, "txt_country", countries_slash)

    beans_clean = item["beans"].strip() or "100% Арабика"
    res_bns = ps_core.ps_set_text(ps_app, "txt_beans", beans_clean)

    height_str = ps_core.format_height(item["height"])
    res_hgt = ps_set_or_hide_height(ps_app, height_str)
    log_fn(f"  │    • Происхождение: Страна={res_cnt} ('{countries_slash}'), Зерно={res_bns}, Высота={res_hgt}")

    # 3. СЛАЙД ФИНАЛЬНЫЙ: оставляем пачки в зависимости от весов линейки (1000 и/или 250)
    res_ttl = ps_core.ps_set_text(ps_app, "txt_title", item["clean_title"])
    log_fn(f"  │    • Финал Заголовок (txt_title): {res_ttl} -> '{item['clean_title']}'")

    packs = item["packs"]
    lineup_weights = item.get("lineup_weights", set())
    any_pack_file = packs.get("1000") or packs.get("250")

    for w_key, so_name, grp_name in [
        ("1000", "so_pack_1000", "grp_pack_1000"),
        ("250", "so_pack_250", "grp_pack_250"),
    ]:
        has_this_weight = (w_key in packs) or (w_key in lineup_weights and any_pack_file is not None)
        pack_file = packs.get(w_key) or (any_pack_file if w_key in lineup_weights else None)

        if has_this_weight and pack_file:
            ps_core.ps_set_visibility(ps_app, grp_name, True)
            ps_core.ps_set_visibility(ps_app, so_name, True)
            r_so = ps_core.ps_replace_so(ps_app, so_name, pack_file)
            log_fn(f"  │    • Финал Пачка {w_key}г: ПОКАЗАНА, замена {so_name}={r_so} <- '{pack_file.name}'")
        else:
            r_vis = ps_core.ps_set_visibility(ps_app, grp_name, False)
            if r_vis == "NOT_FOUND":
                ps_core.ps_set_visibility(ps_app, so_name, False)
            log_fn(f"  │    • Финал Пачка {w_key}г: СКРЫТА (нет веса {w_key}г у линейки)")

    ps_core.ps_save_and_close_current(ps_app)
    log_fn(f"  └─ [✅ Слайды ГОТОВО за {time.time() - t0:.1f}с] -> {out_psd.name}")
    return True