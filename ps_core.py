import csv
import gc
import io
import re
import shutil
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(r"C:\Кирюха\Маркетплейс\Кофе 2. Октябрь 2026\Готовое")
SHEET_ID = "".join(["1lwaSkZjZSLJrVWkwndRe5", "qKSQhR7BzPZJdtgp3LtGxo"])
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
MIN_FREE_SPACE_GB = 2.0


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"-photoroom(?:\.png)?$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\.(?:jpg|jpeg|png|psd|psb)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[/\\\-_,()+.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_free_space_gb(folder: Path = BASE_DIR) -> float:
    return shutil.disk_usage(folder).free / (1024 ** 3)


def format_q_score(raw_q: str) -> tuple[str, str]:
    """Возвращает (число_строкой, слово_БАЛЛ_БАЛЛА_БАЛЛОВ)."""
    val = raw_q.strip().replace(".", ",")
    if not val or "?" in val:
        val = "82,5"
    if "," in val:
        return val, "БАЛЛА"
    digits = re.findall(r"\d+", val)
    if not digits:
        return "82,5", "БАЛЛА"
    n = int(digits[0])
    if 11 <= (n % 100) <= 14:
        word = "БАЛЛОВ"
    elif (n % 10) == 1:
        word = "БАЛЛ"
    elif (n % 10) in (2, 3, 4):
        word = "БАЛЛА"
    else:
        word = "БАЛЛОВ"
    return str(n), word


def format_height(raw_h: str) -> str | None:
    """
    Возвращает строку высоты в правильном порядке ('1100 – 1900 м')
    или None, если высоты в таблице нет (тогда слой скрывается).
    """
    h = raw_h.strip()
    if not h or "?" in h:
        return None
    nums = re.findall(r"\d+", h)
    if len(nums) >= 2:
        return f"{nums[0]} – {nums[1]} м"
    elif len(nums) == 1:
        return f"{nums[0]} м"
    return h


def parse_tastes(raw_taste: str) -> list[str]:
    """Убирает пометки в скобках и троеточия, делит букет вкуса по запятым, '|' или ' и '."""
    cleaned = re.sub(r"\([^)]*\)", "", raw_taste)
    cleaned = cleaned.replace("...", "").strip()
    parts = re.split(r"[,|]+|\s+и\s+", cleaned)
    result = []
    for p in parts:
        p = p.strip(" .")
        if p and p != "?":
            result.append(p[0].upper() + p[1:])
    return result[:4]


def find_folder_for_lineup(lineup_name: str, sku_list: list[str], base_dir: Path = BASE_DIR) -> tuple[int, Path | None]:
    """
    Для папок 1..17 и 19 возвращает саму номерную папку.
    В подпапки артикулов заходит только внутри '18. Одиночки'.
    """
    norm_lineup = normalize(lineup_name)
    aliases = {
        "кармо де минас": 3,
        "мантикора": 3,
        "пибери": 4,
        "луис паоло": 4,
        "guji grade": 16,
        "иргачефф": 17,
        "black edition": 19,
        "primo": 19,
    }

    numbered_folders: dict[int, Path] = {}
    for item in base_dir.iterdir():
        if not item.is_dir():
            continue
        m = re.match(r"^(\d+)\.\s*(.+)$", item.name)
        if not m:
            continue
        num = int(m.group(1))
        numbered_folders[num] = item

    if "одиночки" in norm_lineup or "макдональдс" in norm_lineup:
        if 18 in numbered_folders:
            od_folder = numbered_folders[18]
            for sub in od_folder.iterdir():
                if sub.is_dir():
                    for sku in sku_list:
                        if sub.name.startswith(sku):
                            return 18, sub
                    sub_clean = normalize(re.sub(r"^\d+\s+", "", sub.name))
                    if sub_clean and sub_clean in norm_lineup:
                        return 18, sub
            return 18, od_folder

    for key, num in aliases.items():
        if key in norm_lineup and num in numbered_folders:
            return num, numbered_folders[num]

    for num, folder in numbered_folders.items():
        if num == 18:
            continue
        m = re.match(r"^(\d+)\.\s*(.+)$", folder.name)
        parts = [normalize(p) for p in m.group(2).split("+")]
        for p in parts:
            if p and p in norm_lineup:
                if num == 2 and "black edition" in norm_lineup:
                    continue
                return num, folder

    return 99, None


def find_assets_in_folder(folder: Path, lineup_name: str, rows_info: list[dict]) -> dict:
    """Ищет этикетки 1000г, 250г и файл вкуса -Photoroom.png в папке сорта, 18. Одиночки и корне Готовое."""
    packs: dict[str, Path] = {}
    taste_png: Path | None = None
    target_rows = {str(r["row"]) for r in rows_info}
    clean_lineup = re.sub(r"^одиночки\s+", "", lineup_name, flags=re.IGNORECASE)
    norm_lineup = normalize(clean_lineup)

    short_keys = [norm_lineup]
    for kw in [
        "кармо де минас", "мантикора", "пибери", "guji grade", "иргачефф",
        "dambri", "idido", "sidamo", "бонга", "кихару", "фэнси", "unity",
        "гондурас", "макдональдс"
    ]:
        if kw in norm_lineup:
            short_keys.append(kw)

    search_dirs = [folder]
    if folder.parent != BASE_DIR and folder.parent.name.startswith("18."):
        search_dirs.append(folder.parent)
    if BASE_DIR not in search_dirs:
        search_dirs.append(BASE_DIR)

    for sdir in search_dirs:
        if not sdir.exists():
            continue
        is_dedicated_folder = (
            sdir == folder and sdir != BASE_DIR
            and "+" not in sdir.name and not sdir.name.startswith("18.")
        )

        for f in sdir.iterdir():
            if not f.is_file():
                continue
            low = f.name.lower()
            fname_norm = normalize(f.name)

            if low.endswith("-photoroom.png") and not low.startswith("gemini_"):
                if any(k in fname_norm for k in short_keys) or is_dedicated_folder:
                    if taste_png is None:
                        taste_png = f

            elif low.endswith((".jpg", ".jpeg")) and "упаковка" not in low and "нету" not in low:
                row_prefix = re.match(r"^((?:\d+\.\s*)+)", f.name)
                file_rows = set(re.findall(r"\d+", row_prefix.group(1))) if row_prefix else set()

                is_match = bool(file_rows & target_rows) or any(k in fname_norm for k in short_keys) or is_dedicated_folder
                if "black edition" in norm_lineup and "black edition" not in fname_norm and not (file_rows & target_rows):
                    is_match = False
                if "black edition" not in norm_lineup and "black edition" in fname_norm:
                    is_match = False

                if not is_match:
                    continue

                if re.search(r"(?:1000|1\s*кг)", low):
                    packs.setdefault("1000", f)
                elif re.search(r"(?:250|0[.,]25)", low):
                    packs.setdefault("250", f)
                else:
                    matched_by_row = False
                    for r in rows_info:
                        if str(r["row"]) in file_rows:
                            packs.setdefault(r["weight"], f)
                            matched_by_row = True
                    if not matched_by_row:
                        for r in rows_info:
                            packs.setdefault(r["weight"], f)

    return {"packs": packs, "taste": taste_png}


def load_all_lineups() -> list[dict]:
    req = urllib.request.Request(SHEET_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = resp.read().decode("utf-8-sig")

    reader = csv.reader(io.StringIO(content))
    next(reader, [])

    grouped: dict[str, list[dict]] = {}
    for row_idx, row in enumerate(reader, start=2):
        if len(row) < 17:
            continue
        sku = row[0].strip()
        lineup = row[3].strip()
        if not sku or not lineup:
            continue
        grouped.setdefault(lineup, []).append({
            "row": row_idx,
            "sku": sku,
            "need": row[1].strip(),
            "brand": row[2].strip(),
            "lineup": lineup,
            "kind": "молотый" if "молот" in row[4].strip().lower() else "зерно",
            "weight": row[6].strip(),
            "beans": row[8].strip(),
            "country": row[9].strip(),
            "region": row[10].strip(),
            "height": row[11].strip(),
            "acidity": row[12].strip(),
            "strength": row[13].strip(),
            "roast": row[14].strip(),
            "qscore": row[15].strip(),
            "taste": row[16].strip(),
        })

    # Эталонные данные из "Бразилия Моджиана" (строки 13-16) для "Black Edition Бразилия Моджиана"
    mogiana_ref = grouped.get("Бразилия Моджиана", [{}])[0]

    items = []
    for lineup_name, rows in grouped.items():
        skus = [r["sku"] for r in rows]
        folder_num, folder_path = find_folder_for_lineup(lineup_name, skus, BASE_DIR)
        assets = find_assets_in_folder(folder_path, lineup_name, rows) if folder_path else {"packs": {}, "taste": None}

        # Собираем первые непустые значения со всех строк линейки
        def pick_field(key: str) -> str:
            for r in rows:
                v = r.get(key, "").strip()
                if v and v != "?":
                    return v
            return rows[0].get(key, "").strip()

        beans = pick_field("beans")
        country = pick_field("country")
        height = pick_field("height")
        acidity = pick_field("acidity")
        strength = pick_field("strength")
        roast = pick_field("roast")
        qscore = pick_field("qscore")
        taste_raw = pick_field("taste")

        # Для Black Edition Бразилия Моджиана берем параметры и высоту (850-1000 м) как у желтой Бразилия Моджиана (строки 13-16)
        if "black edition" in normalize(lineup_name) and mogiana_ref:
            height = mogiana_ref.get("height", "850-1000 м")
            if not acidity or "?" in acidity:
                acidity = mogiana_ref.get("acidity", "3")
            if not strength or "?" in strength:
                strength = mogiana_ref.get("strength", "3")
            if not roast or "?" in roast:
                roast = mogiana_ref.get("roast", "3")
            if not qscore or "?" in qscore:
                qscore = mogiana_ref.get("qscore", "82,5")
            if not taste_raw or "?" in taste_raw:
                taste_raw = mogiana_ref.get("taste", "фундук, какао, спелый апельсин")

        clean_title = re.sub(r"^Одиночки\s+", "", lineup_name, flags=re.IGNORECASE).strip()
        lineup_weights = {r["weight"] for r in rows if r["weight"] in ("1000", "250")}

        items.append({
            "folder_num": folder_num,
            "folder": folder_path,
            "lineup": lineup_name,
            "clean_title": clean_title,
            "rows": rows,
            "lineup_weights": lineup_weights,
            "packs": assets["packs"],
            "taste_png": assets["taste"],
            "has_packs": bool(assets["packs"]),
            "has_taste": assets["taste"] is not None,
            "beans": beans,
            "country": country,
            "height": height,
            "acidity": acidity,
            "strength": strength,
            "roast": roast,
            "qscore": qscore,
            "taste_raw": taste_raw,
        })

    items.sort(key=lambda x: (x["folder_num"], x["lineup"]))
    return items


# ==================== ФУНКЦИИ PHOTOSHOP ====================

def get_ps_app():
    import win32com.client
    ps = win32com.client.Dispatch("Photoshop.Application")
    ps.DisplayDialogs = 3
    return ps


def ps_purge_memory(ps_app):
    """Очищает только историю и отмену в ФШ, НЕ трогая системный буфер обмена Windows (скрины работают!)."""
    jsx = r"""
    (function() {
        try { app.purge(PurgeTarget.UNDOCACHES); } catch(e) {}
        try { app.purge(PurgeTarget.HISTORYCACHES); } catch(e) {}
        return "PURGED";
    })();
    """
    try:
        ps_app.DoJavaScript(jsx)
    except Exception:
        pass
    gc.collect()
    time.sleep(0.3)


def ps_open_copy_safely(ps_app, template_path: Path, out_psd_path: Path):
    """Копирует шаблон в целевую папку и открывает копию. Мастер-шаблон не затрагивается."""
    shutil.copy2(str(template_path), str(out_psd_path))
    ps_app.Open(str(out_psd_path))


def ps_replace_so(ps_app, layer_name: str, file_path: Path) -> str:
    """
    Заменяет смарт-объекты 1-в-1 без уменьшения из-за разницы 72 DPI и 300 DPI.
    Сначала меняет DPI с ResampleMethod.NONE (сохраняя пиксели), затем подгоняет размер
    под внутренний холст смарт-объекта. Маска, поворот 0,49° и связи слоев 🔗 не сбиваются.
    """
    temp_ext = ".png" if file_path.suffix.lower() == ".png" else ".jpg"
    temp_file = BASE_DIR / f"_temp_so_replace{temp_ext}"
    escaped_src = str(file_path).replace("\\", "\\\\")
    escaped_tmp = str(temp_file).replace("\\", "\\\\")
    prefix = layer_name.strip().lower()

    jsx = f"""
    (function() {{
        var doc = app.activeDocument;
        var matches = [];
        var allSO = [];
        var pref = "{prefix}";

        function walk(parent) {{
            for (var i = 0; i < parent.layers.length; i++) {{
                var lyr = parent.layers[i];
                if (lyr.kind == LayerKind.SMARTOBJECT) {{
                    allSO.push(lyr.name);
                    var cleanName = lyr.name.replace(/^\\s+|\\s+$/g, "").toLowerCase();
                    if (cleanName === pref || cleanName.indexOf(pref + " ") === 0 || cleanName.indexOf(pref + "_") === 0) {{
                        matches.push(lyr);
                    }}
                }}
                if (lyr.typename === "LayerSet") walk(lyr);
            }}
        }}
        walk(doc);
        if (matches.length === 0) {{
            return "НЕ_НАЙДЕН (В PSD есть: " + allSO.join(", ") + ")";
        }}

        var origRuler = app.preferences.rulerUnits;
        app.preferences.rulerUnits = Units.PIXELS;

        var replaced = 0;
        var lastErr = "";

        for (var k = 0; k < matches.length; k++) {{
            try {{
                var target = matches[k];
                var wasVis = target.visible;
                target.visible = true;
                target.allLocked = false;
                doc.activeLayer = target;

                // 1. Узнаем точные пиксели и родной DPI внутри смарт-объекта шаблона
                var idEdit = stringIDToTypeID("placedLayerEditContents");
                executeAction(idEdit, new ActionDescriptor(), DialogModes.NO);
                var soDoc = app.activeDocument;
                var targetW = soDoc.width.as("px");
                var targetH = soDoc.height.as("px");
                var targetRes = soDoc.resolution;
                soDoc.close(SaveOptions.DONOTSAVECHANGES);

                // 2. Открываем новую пачку, СНАЧАЛА меняем DPI без ресемплинга (чтобы ФШ не сжал в 4.16 раза!)
                var imgDoc = app.open(new File("{escaped_src}"));
                imgDoc.resizeImage( undefined, undefined, targetRes, ResampleMethod.NONE );
                if (Math.abs(imgDoc.width.as("px") - targetW) > 1 || Math.abs(imgDoc.height.as("px") - targetH) > 1) {{
                    imgDoc.resizeImage(UnitValue(targetW, "px"), UnitValue(targetH, "px"), targetRes, ResampleMethod.BICUBIC);
                }}

                var tmpFileObj = new File("{escaped_tmp}");
                if ("{temp_ext}" === ".png") {{
                    var pngOpts = new PNGSaveOptions();
                    imgDoc.saveAs(tmpFileObj, pngOpts, true, Extension.LOWERCASE);
                }} else {{
                    var jpgOpts = new JPEGSaveOptions();
                    jpgOpts.quality = 12;
                    imgDoc.saveAs(tmpFileObj, jpgOpts, true, Extension.LOWERCASE);
                }}
                imgDoc.close(SaveOptions.DONOTSAVECHANGES);

                // 3. Заменяем содержимое подготовленным файлом с тем же DPI (встает 1-в-1)
                app.activeDocument = doc;
                doc.activeLayer = target;
                var idReplace = stringIDToTypeID("placedLayerReplaceContents");
                var desc = new ActionDescriptor();
                desc.putPath(charIDToTypeID("null"), tmpFileObj);
                executeAction(idReplace, desc, DialogModes.NO);

                target.visible = wasVis;
                replaced++;
            }} catch(e) {{
                lastErr = e.message;
                try {{ app.activeDocument = doc; }} catch(e2) {{}}
            }}
        }}

        app.preferences.rulerUnits = origRuler;
        if (replaced === 0) return "ОШИБКА: " + lastErr;
        return "ОК (1-в-1, обновлено слоев: " + replaced + ")";
    }})();
    """
    res = ps_app.DoJavaScript(jsx)
    if temp_file.exists():
        try:
            temp_file.unlink()
        except Exception:
            pass
    return res


def ps_set_text(ps_app, layer_name: str, new_text: str) -> str:
    safe_text = new_text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\r").replace("\r", "\\r")
    prefix = layer_name.strip().lower()
    jsx = f"""
    (function() {{
        var doc = app.activeDocument;
        var matches = [];
        var pref = "{prefix}";
        function walk(parent) {{
            for (var i = 0; i < parent.layers.length; i++) {{
                var lyr = parent.layers[i];
                if (lyr.kind == LayerKind.TEXT) {{
                    var cleanName = lyr.name.replace(/^\\s+|\\s+$/g, "").toLowerCase();
                    if (cleanName === pref || cleanName.indexOf(pref + " ") === 0) matches.push(lyr);
                }}
                if (lyr.typename === "LayerSet") walk(lyr);
            }}
        }}
        walk(doc);
        if (matches.length === 0) return "NOT_FOUND";
        for (var k = 0; k < matches.length; k++) {{
            matches[k].textItem.contents = "{safe_text}";
        }}
        return "OK";
    }})();
    """
    return ps_app.DoJavaScript(jsx)


def ps_set_visibility(ps_app, item_name: str, visible: bool) -> str:
    vis_str = "true" if visible else "false"
    prefix = item_name.strip().lower()
    jsx = f"""
    (function() {{
        var doc = app.activeDocument;
        var foundCount = 0;
        var pref = "{prefix}";
        function walk(parent) {{
            for (var i = 0; i < parent.layers.length; i++) {{
                var lyr = parent.layers[i];
                var cleanName = lyr.name.replace(/^\\s+|\\s+$/g, "").toLowerCase();
                if (cleanName === pref || cleanName.indexOf(pref + " ") === 0) {{
                    lyr.visible = {vis_str};
                    foundCount++;
                }}
                if (lyr.typename === "LayerSet") walk(lyr);
            }}
        }}
        walk(doc);
        return foundCount > 0 ? "OK" : "NOT_FOUND";
    }})();
    """
    return ps_app.DoJavaScript(jsx)


def ps_save_and_close_current(ps_app):
    """Сохраняет открытую рабочую копию PSD и закрывает её без очистки буфера обмена Windows."""
    jsx = r"""
    (function() {
        var doc = app.activeDocument;
        doc.save();
        doc.close(SaveOptions.DONOTSAVECHANGES);
        try { app.purge(PurgeTarget.UNDOCACHES); } catch(e) {}
        try { app.purge(PurgeTarget.HISTORYCACHES); } catch(e) {}
        return "SAVED";
    })();
    """
    ps_app.DoJavaScript(jsx)
    gc.collect()
    time.sleep(0.3)


def ps_save_and_close(ps_app, out_path: Path):
    """Совместимость на случай вызова со старыми аргументами."""
    ps_save_and_close_current(ps_app)