from __future__ import annotations

from html import escape


def to_markdown(result: dict) -> str:
    c = result["card"]
    p = result["product"]
    L: list[str] = []
    if result["status"] != "ok":
        L += ["> ⚠️ **Требует ручной проверки** — автоматические проверки не пройдены:"]
        L += [f"> - {w}" for w in result["warnings"]]
        L += [""]
    L += [f"# {c['seo_title']}", f"*{c['seo_title_length']} симв. · {p['name'] or 'название не указано'}*", ""]
    imgs = result.get("images") or []
    if imgs:
        L += [f"![{c['seo_title']}]({imgs[0]})", ""]
    L += ["## SEO-описание", "", c["seo_description"], ""]
    note = f" — {c['description_too_short_reason']}" if c["description_too_short_reason"] else ""
    L += [f"*{c['seo_description_length']} симв.{note}*", ""]
    L += ["## Ключевые характеристики", "", "| Характеристика | Значение |", "|---|---|"]
    L += [f"| {r['name']} | {r['value']} |" for r in c["key_characteristics"]]
    if len(imgs) > 1 or result.get("source_url"):
        L += ["", "## Фото и источник", ""]
        if result.get("source_url"):
            L += [f"Страница товара: {result['source_url']}", ""]
        L += [f"![фото {i}]({u})" for i, u in enumerate(imgs[1:], 2)]
    L += ["", "## Поисковые запросы", ""] + [f"- {q}" for q in c["search_queries"]]
    L += ["", "## Для менеджера", "", "**Кому подходит:**"] + [f"- {x}" for x in c["commercial"]["suitable_for"]]
    L += ["", "**Какие задачи решает:**"] + [f"- {x}" for x in c["commercial"]["tasks"]]
    if c["manager_notes"]:
        L += ["", f"**Замечания:** {c['manager_notes']}"]
    L += ["", "## Что нужно уточнить", ""]
    gaps = [f"Во входных данных не заполнено: `{f}`" for f in result["missing_input_fields"]]
    gaps += [f"{m['field']} — {m.get('why', '')}".rstrip(" —") for m in c["missing_data"]]
    L += [f"- {g}" for g in gaps] if gaps else ["- Нет замечаний по полноте данных."]
    return "\n".join(L) + "\n"


_CSS = """body{font:16px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#222}
h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:1.8rem;border-bottom:1px solid #ddd;padding-bottom:.2rem}
.main{max-width:100%;max-height:420px;border-radius:8px;border:1px solid #ddd}
.gallery img{height:120px;margin:0 .5rem .5rem 0;border-radius:6px;border:1px solid #ddd}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:.35rem .6rem;text-align:left}
.nodata{color:#a00}.warn{background:#fff3cd;border:1px solid #e0c36a;padding:.6rem 1rem;border-radius:6px}
.meta{color:#777;font-size:.9rem}"""


def to_html(result: dict) -> str:
    """Самодостаточная HTML-страница карточки (фото по ссылкам из фида)."""
    e = escape
    c, p = result["card"], result["product"]
    imgs = result.get("images") or []
    H = ["<!doctype html><html lang='ru'><head><meta charset='utf-8'>",
         f"<title>{e(c['seo_title'])}</title><style>{_CSS}</style></head><body>"]
    if result["status"] != "ok":
        H.append("<div class='warn'><b>Требует ручной проверки:</b><ul>"
                 + "".join(f"<li>{e(w)}</li>" for w in result["warnings"]) + "</ul></div>")
    H.append(f"<h1>{e(c['seo_title'])}</h1><p class='meta'>{c['seo_title_length']} симв. · "
             f"{e(p['name'] or 'название не указано')}</p>")
    if imgs:
        H.append(f"<img class='main' src='{e(imgs[0], quote=True)}' alt='{e(c['seo_title'], quote=True)}'>")
    H.append("<h2>Описание</h2>" + "".join(f"<p>{e(x)}</p>" for x in c["seo_description"].split("\n\n")))
    H.append(f"<p class='meta'>{c['seo_description_length']} симв.</p>")
    H.append("<h2>Характеристики</h2><table>" + "".join(
        f"<tr><td>{e(r['name'])}</td><td class='{'nodata' if r['value'] == 'данных нет' else ''}'>{e(r['value'])}</td></tr>"
        for r in c["key_characteristics"]) + "</table>")
    H.append("<h2>Поисковые запросы</h2><ul>" + "".join(f"<li>{e(q)}</li>" for q in c["search_queries"]) + "</ul>")
    H.append("<h2>Для менеджера</h2><p><b>Кому подходит:</b></p><ul>"
             + "".join(f"<li>{e(x)}</li>" for x in c["commercial"]["suitable_for"]) + "</ul>"
             "<p><b>Какие задачи решает:</b></p><ul>"
             + "".join(f"<li>{e(x)}</li>" for x in c["commercial"]["tasks"]) + "</ul>")
    gaps = [f"Во входных данных не заполнено: {f}" for f in result["missing_input_fields"]]
    gaps += [f"{m['field']} — {m.get('why', '')}" for m in c["missing_data"]]
    H.append("<h2>Что нужно уточнить</h2><ul>" + "".join(f"<li>{e(g)}</li>" for g in gaps) + "</ul>")
    if len(imgs) > 1:
        H.append("<h2>Фото</h2><div class='gallery'>" + "".join(
            f"<img src='{e(u, quote=True)}' alt=''>" for u in imgs[1:]) + "</div>")
    if result.get("source_url"):
        H.append(f"<p class='meta'>Страница товара: <a href='{e(result['source_url'], quote=True)}'>{e(result['source_url'])}</a></p>")
    H.append("</body></html>")
    return "\n".join(H)
