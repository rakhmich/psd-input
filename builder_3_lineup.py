import re
import time
import ps_core

TEMPLATE_LINEUP = ps_core.BASE_DIR / "ШАБЛОН_Линейка.psd"


def pick_three_other_lineups(current_item: dict, all_ready_items: list[dict], index_offset: int) -> list[dict]:
    """Подбирает 3 разных сорта (не совпадающих с текущим и с разными вкусами) по кругу."""
    candidates = [
        it for it in all_ready_items
        if it["lineup"] != current_item["lineup"] and it["has_packs"]
    ]
    if len(candidates) < 3:
        return candidates

    chosen = []
    used_tastes = set()
    n = len(candidates)
    for step in range(n):
        cand = candidates[(index_offset * 3 + step) % n]
        t_sig = cand["taste_raw"].strip().lower()
        if t_sig not in used_tastes or len(chosen) + (n - step) <= 3:
            chosen.append(cand)
            used_tastes.add(t_sig)
        if len(chosen) == 3:
            break
    return chosen


def build_lineup_for_item(
    ps_app, item: dict, all_ready_items: list[dict], idx_offset: int, log_fn, force_rebuild: bool = False
) -> bool:
    """Собирает файл Линейка_<Линейка>.psd из 3 неповторяющихся сортов."""
    if not TEMPLATE_LINEUP.exists():
        log_fn(f"  [!] ОШИБКА: Не найден шаблон {TEMPLATE_LINEUP.name}")
        return False

    lineup = item["lineup"]
    folder = item["folder"]
    if not folder:
        return False

    safe_name = re.sub(r'[\\/*?:"<>|]', "_", lineup)
    out_psd = folder / f"Линейка_{safe_name}.psd"

    if out_psd.exists() and not force_rebuild:
        log_fn(f"  ├─ [Линейка] Уже существует: {out_psd.name} -> Пропуск")
        return True

    trio = pick_three_other_lineups(item, all_ready_items, idx_offset)
    if len(trio) < 3:
        log_fn("  [!] Недостаточно готовых сортов для составления тройки линейки")
        return False

    t0 = time.time()
    log_fn(f"  ├─ [Линейка] Собираем витрину из 3 сортов: {', '.join(c['clean_title'] for c in trio)}")
    ps_core.ps_open_copy_safely(ps_app, TEMPLATE_LINEUP, out_psd)

    for slot_idx, cand in enumerate(trio, start=1):
        pack_file = cand["packs"].get("1000") or cand["packs"].get("250")
        if pack_file:
            r_so = ps_core.ps_replace_so(ps_app, f"so_pack_{slot_idx}", pack_file)
            log_fn(f"  │    • Слот #{slot_idx} ({cand['clean_title']}): пачка={r_so}")
        ps_core.ps_set_text(ps_app, f"txt_title_{slot_idx}", cand["clean_title"])
        ps_core.ps_set_text(ps_app, f"txt_beans_{slot_idx}", cand["beans"] or "100% Арабика")
        tastes_list = ps_core.parse_tastes(cand["taste_raw"])
        ps_core.ps_set_text(ps_app, f"txt_taste_{slot_idx}", ", ".join(tastes_list))

    ps_core.ps_save_and_close_current(ps_app)
    log_fn(f"  └─ [✅ Линейка ГОТОВО за {time.time() - t0:.1f}с] -> {out_psd.name}")
    return True