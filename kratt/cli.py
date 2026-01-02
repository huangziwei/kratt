from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from opencc import OpenCC


UNKNOWN_DATE_KEY = (10**9, 10**9)


@dataclass(frozen=True)
class Book:
    work_id: str
    title: str
    dynasty_label: str
    author_label: str
    rel_path: str
    path: Path
    date_not_before: int | None
    date_not_after: int | None


@dataclass(frozen=True)
class Match:
    book: Book
    line_no: int
    offset: int
    term: str
    line: str


def resolve_data_dir(explicit: str | None) -> Path:
    if explicit:
        data_dir = Path(explicit)
        if not (data_dir / "books.csv").exists():
            raise FileNotFoundError(f"books.csv not found in {data_dir}")
        return data_dir

    cwd_data = Path.cwd() / "data"
    if (cwd_data / "books.csv").exists():
        return cwd_data

    package_root = Path(__file__).resolve().parents[1]
    package_data = package_root / "data"
    if (package_data / "books.csv").exists():
        return package_data

    raise FileNotFoundError("could not locate data directory (expected data/books.csv)")


def load_date_ranges(path: Path) -> dict[str, tuple[int, int]]:
    ranges: dict[str, tuple[int, int]] = {}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            work_id = (row.get("work_id") or "").strip()
            if not work_id:
                continue
            try:
                date_not_before = int(row["date_not_before"])
                date_not_after = int(row["date_not_after"])
            except (TypeError, ValueError):
                continue
            current = ranges.get(work_id)
            candidate = (date_not_before, date_not_after)
            if current is None or candidate < current:
                ranges[work_id] = candidate
    return ranges


def load_books(data_dir: Path, date_ranges: dict[str, tuple[int, int]]) -> list[Book]:
    books: list[Book] = []
    with (data_dir / "books.csv").open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rel_path = (row.get("path") or "").strip()
            if not rel_path:
                continue
            path = data_dir / rel_path
            date_range = date_ranges.get((row.get("work_id") or "").strip())
            date_not_before = date_range[0] if date_range else None
            date_not_after = date_range[1] if date_range else None
            books.append(
                Book(
                    work_id=(row.get("work_id") or "").strip(),
                    title=(row.get("title") or "").strip(),
                    dynasty_label=(row.get("dynasty_label") or "").strip(),
                    author_label=(row.get("author_label") or "").strip(),
                    rel_path=rel_path,
                    path=path,
                    date_not_before=date_not_before,
                    date_not_after=date_not_after,
                )
            )
    books.sort(key=book_sort_key)
    return books


def book_sort_key(book: Book) -> tuple[int, int, str, str]:
    if book.date_not_before is None or book.date_not_after is None:
        date_key = UNKNOWN_DATE_KEY
    else:
        date_key = (book.date_not_before, book.date_not_after)
    return (*date_key, book.work_id, book.rel_path)


def term_variants(term: str) -> list[str]:
    s2t = OpenCC("s2t")
    t2s = OpenCC("t2s")
    variants = {term.strip()}
    variants.add(s2t.convert(term))
    variants.add(t2s.convert(term))
    variants = {variant for variant in variants if variant}
    return sorted(variants)


def iter_line_matches(line: str, variants: list[str]) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for term in variants:
        start = 0
        term_len = len(term)
        if term_len == 0:
            continue
        while True:
            idx = line.find(term, start)
            if idx == -1:
                break
            matches.append((idx, term))
            start = idx + term_len
    matches.sort(key=lambda item: (item[0], item[1]))
    return matches


def iter_matches(
    book: Book, variants: list[str], max_matches: int | None = None
) -> Iterator[Match]:
    if not book.path.exists():
        return
    remaining = max_matches
    with book.path.open(encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            for offset, term in iter_line_matches(line, variants):
                yield Match(
                    book=book,
                    line_no=line_no,
                    offset=offset,
                    term=term,
                    line=line,
                )
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        return


def render_snippet(line: str, offset: int, term: str, context: int) -> str:
    line = line.replace("\t", " ").rstrip()
    context = max(context, 0)
    start = max(0, offset - context)
    end = min(len(line), offset + len(term) + context)
    prefix = line[start:offset]
    match = line[offset : offset + len(term)]
    suffix = line[offset + len(term) : end]
    left_marker = "..." if start > 0 else ""
    right_marker = "..." if end < len(line) else ""
    return f"{left_marker}{prefix}[{match}]{suffix}{right_marker}".strip()


def format_date_range(book: Book) -> str:
    if book.date_not_before is None or book.date_not_after is None:
        return "unknown"
    return f"{book.date_not_before}..{book.date_not_after}"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find earliest attestations in the dataset.")
    parser.add_argument("term", help="Query term to search for.")
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        help="Maximum number of results to return (default: 10).",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=30,
        help="Number of characters to include around the match (default: 30).",
    )
    parser.add_argument(
        "--data-dir",
        help="Path to the data directory (default: auto-detect).",
    )
    parser.add_argument(
        "--dedup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show only the first hit per work (default: enabled).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    term = args.term.strip()
    if not term:
        parser.error("term must be non-empty")
    if args.limit < 1:
        parser.error("limit must be >= 1")

    try:
        data_dir = resolve_data_dir(args.data_dir)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    date_ranges = load_date_ranges(data_dir / "publication_date_range.csv")
    books = load_books(data_dir, date_ranges)
    variants = term_variants(term)

    results: list[Match] = []
    for book in books:
        remaining = args.limit - len(results)
        if remaining <= 0:
            break
        per_book_limit = 1 if args.dedup else remaining
        for match in iter_matches(book, variants, per_book_limit):
            results.append(match)

    print(f"query: {term}")
    print(f"variants: {', '.join(variants)}")
    print(f"limit: {args.limit}")
    print(f"dedup: {'on' if args.dedup else 'off'}")
    print(f"results: {len(results)}")
    print()

    for idx, match in enumerate(results, 1):
        book = match.book
        date_label = format_date_range(book)
        author_label = book.author_label or "-"
        dynasty_label = book.dynasty_label or "-"
        location = f"{book.rel_path}:{match.line_no}"
        snippet = render_snippet(match.line, match.offset, match.term, args.context)
        print(
            f"{idx}) {date_label} | {book.work_id} | {book.title} | {dynasty_label} | "
            f"{author_label} | {location}"
        )
        print(f"    {snippet}")

    if not results:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
