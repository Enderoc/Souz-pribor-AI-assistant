from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .llm import LLMError, create_client
from .pipeline import generate_card
from .render import to_html, to_markdown
from .feed import DEFAULT_FEED_URL, inspect_feed, select_offers
from .schema import InputError, load_products, parse_product


def _read_inputs(paths: list[str]) -> list[tuple[str, str]]:
    """Возвращает [(источник, текст)]. «-» — stdin; каталог — все *.json внутри."""
    out = []
    for p in paths:
        if p == "-":
            out.append(("stdin", sys.stdin.read()))
            continue
        path = Path(p)
        if not path.exists():
            raise InputError(f"Файл или каталог не найден: {p}")
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        if not files:
            raise InputError(f"В каталоге {p} нет *.json файлов.")
        for f in files:
            try:
                out.append((f.name, f.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError) as e:
                raise InputError(f"Не удалось прочитать {f}: {e}") from e
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cardgen", description="Черновик карточки товара КИП по JSON.")
    ap.add_argument("inputs", nargs="*", help="JSON-файл(ы), каталог или «-» для stdin")
    ap.add_argument("--feed", nargs="?", const=DEFAULT_FEED_URL,
                    help="YML-фид (URL или файл) вместо JSON-входа; без значения — фид souz-pribor.ru (или FEED_URL из .env)")
    ap.add_argument("--search", help="с --feed: подстрока в названии товара")
    ap.add_argument("--offer-id", action="append", help="с --feed: id товара (можно несколько раз)")
    ap.add_argument("--min-specs", type=int, default=0, help="с --feed: брать товары, у которых заполнено не меньше N параметров")
    ap.add_argument("--inspect", action="store_true", help="с --feed: показать структуру первого <offer> и выйти")
    ap.add_argument("--limit", type=int, default=2, help="с --feed: сколько товаров взять (по умолчанию 2)")
    ap.add_argument("-o", "--out", default="out", help="каталог для результатов (по умолчанию out/)")
    ap.add_argument("-f", "--format", choices=["json", "md", "html", "all"], default="all")
    ap.add_argument("--provider", choices=["anthropic", "openai"], help="LLM-провайдер (иначе LLM_PROVIDER или по найденному ключу)")
    ap.add_argument("--model", help="модель (иначе ANTHROPIC_MODEL / OPENAI_MODEL или значение по умолчанию)")
    ap.add_argument("--dry-run", action="store_true", help="только проверить вход, без вызова LLM")
    args = ap.parse_args(argv)

    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        print("Предупреждение: пакет python-dotenv не установлен, файл .env не читается. "
              "Выполните: pip install -r requirements.txt", file=sys.stderr)
    else:
        # ищем .env в текущей папке, затем в корне проекта (две папки выше src/cardgen)
        candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
        env_file = next((c for c in candidates if c.is_file()), None) or find_dotenv(usecwd=True)
        if env_file:
            load_dotenv(env_file)
        else:
            print("Предупреждение: файл .env не найден (искали в " + ", ".join(str(c.parent) for c in candidates)
                  + "). Создайте его из .env.example.", file=sys.stderr)

    if args.inspect:
        if not args.feed:
            ap.error("--inspect работает вместе с --feed")
        try:
            print(inspect_feed(args.feed))
        except InputError as e:
            print(f"Ошибка ввода: {e}", file=sys.stderr)
            return 2
        return 0

    try:
        if args.feed:
            raws = select_offers(os.environ.get("FEED_URL") or args.feed if args.feed == DEFAULT_FEED_URL else args.feed,
                                  args.search, args.offer_id, args.limit, args.min_specs)
            sources = [(f"offer_{r['_offer_id'] or i}.json",
                        json.dumps({k: v for k, v in r.items() if k != "_offer_id"}, ensure_ascii=False))
                       for i, r in enumerate(raws, 1)]
        elif args.inputs:
            sources = _read_inputs(args.inputs)
        else:
            ap.error("укажите JSON-вход или --feed")
    except InputError as e:
        print(f"Ошибка ввода: {e}", file=sys.stderr)
        return 2

    client = None
    if not args.dry_run:
        try:
            client = create_client(args.provider, args.model)
        except LLMError as e:
            print(f"Ошибка настройки: {e}", file=sys.stderr)
            return 2

    out_dir = Path(args.out)
    done = failed = 0
    for src, text in sources:
        try:
            raws = load_products(text)
        except InputError as e:
            print(f"[{src}] ✗ {e}", file=sys.stderr)
            failed += 1
            continue
        for i, raw in enumerate(raws, 1):
            label = src if len(raws) == 1 else f"{src}#{i}"
            try:
                product, missing = parse_product(raw)
            except InputError as e:
                print(f"[{label}] ✗ {e}", file=sys.stderr)
                failed += 1
                continue
            if args.dry_run:
                print(f"[{label}] ✓ вход корректен: {product.name or 'без названия'}; пропущено: {missing or 'ничего'}")
                done += 1
                continue
            try:
                result = generate_card(product, missing, client)
            except LLMError as e:
                print(f"[{label}] ✗ {e}", file=sys.stderr)
                failed += 1
                continue
            stem = Path(src).stem + ("" if len(raws) == 1 else f"_{i}")
            out_dir.mkdir(parents=True, exist_ok=True)
            if args.format in ("json", "all"):
                (out_dir / f"{stem}.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if args.format in ("md", "all"):
                (out_dir / f"{stem}.md").write_text(to_markdown(result), encoding="utf-8")
            if args.format in ("html", "all"):
                (out_dir / f"{stem}.html").write_text(to_html(result), encoding="utf-8")
            flag = "✓" if result["status"] == "ok" else "⚠ требует проверки"
            print(f"[{label}] {flag} → {out_dir / stem}.* (попыток: {result['attempts']})")
            done += 1
    print(f"Готово: {done}, с ошибкой: {failed}")
    return 0 if failed == 0 else 1
