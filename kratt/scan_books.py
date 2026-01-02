from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


BOOK_RE = re.compile(r"^(KR\d[a-z]\d{4})\s+(.+)\.txt$")
WORK_RE = re.compile(r"^\*\*\*\s+(KR\d[a-z]\d{4})\b")
PEOPLE_SECTION_RE = re.compile(r"^\*\*\*\*\s+人物\b")
HEADING4_RE = re.compile(r"^\*\*\*\*\s+")
PERSON_RE = re.compile(r"^\*\*\*\*\*\s+(.+)$")
PROPERTY_RE = re.compile(r"^\s*:([A-Z_]+):\s*(.*)$")
DATE_NUMBER_RE = re.compile(r"-?\d{1,4}")
PAREN_RE = re.compile(r"[（(][^）)]*[）)]")

# Heuristic dynasty ranges; adjust via --dynasty-ranges if needed.
DEFAULT_DYNASTY_RANGES: dict[str, tuple[int, int]] = {
    "西周": (-1046, -771),
    "東周": (-770, -256),
    "周": (-1046, -256),
    "春秋": (-770, -476),
    "戰國": (-475, -221),
    "秦": (-221, -206),
    "西漢": (-206, 8),
    "新": (9, 23),
    "東漢": (25, 220),
    "漢": (-206, 220),
    "三國": (220, 280),
    "魏": (220, 266),
    "蜀": (221, 263),
    "吳": (229, 280),
    "西晉": (266, 316),
    "東晉": (317, 420),
    "晉": (266, 420),
    "北魏": (386, 534),
    "東魏": (534, 550),
    "西魏": (535, 557),
    "北齊": (550, 577),
    "北周": (557, 581),
    "劉宋": (420, 479),
    "南齊": (479, 502),
    "梁": (502, 557),
    "陳": (557, 589),
    "南北朝": (420, 589),
    "南朝": (420, 589),
    "北朝": (386, 581),
    "隋": (581, 618),
    "唐": (618, 907),
    "五代": (907, 960),
    "五代十國": (907, 979),
    "北宋": (960, 1127),
    "南宋": (1127, 1279),
    "宋": (960, 1279),
    "遼": (907, 1125),
    "西夏": (1038, 1227),
    "金": (1115, 1234),
    "元": (1271, 1368),
    "明": (1368, 1644),
    "清": (1644, 1912),
    "民國": (1912, 1949),
}

DYNASTY_ALIASES = {
    "前漢": "西漢",
    "後漢": "東漢",
    "蜀漢": "蜀",
    "東吳": "吳",
    "孫吳": "吳",
    "南朝宋": "劉宋",
    "宋(南朝)": "劉宋",
}

PREFERRED_FUNCTIONS = {
    "撰",
    "著",
    "編",
    "纂",
    "輯",
    "譯",
    "注",
    "註",
    "疏",
    "述",
    "校",
    "校訂",
    "考",
    "考補",
    "解",
    "傳",
    "音義",
}

UNKNOWN_AUTHOR_MARKERS = {
    "佚名",
    "闕名",
    "不詳",
    "未知",
    "失名",
    "不著撰人",
    "作者不詳",
    "不知撰人",
}


@dataclass(frozen=True)
class Book:
    collection: str
    work_id: str
    title: str
    dynasty_label: str
    author_label: str
    filename: str
    path: str


@dataclass(frozen=True)
class PersonEvidence:
    work_id: str
    person_name: str
    function: str
    dynasty_label: str
    raw_dates: str
    date_not_before: int | None
    date_not_after: int | None


@dataclass(frozen=True)
class CBDBPerson:
    person_id: str
    name: str
    birth_year: int | None
    death_year: int | None
    fl_earliest: int | None
    fl_latest: int | None


def parse_filename(name: str) -> Book | None:
    match = BOOK_RE.match(name)
    if not match:
        return None
    work_id, rest = match.groups()
    title, dynasty_label, author_label = parse_metadata(rest)
    collection = work_id[:3]
    return Book(
        collection=collection,
        work_id=work_id,
        title=title,
        dynasty_label=dynasty_label,
        author_label=author_label,
        filename=name,
        path="",
    )


def parse_metadata(label: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in label.rsplit("-", 2)]
    if len(parts) == 3:
        title, dynasty_label, author_label = parts
    elif len(parts) == 2:
        title, dynasty_label = parts
        author_label = ""
    else:
        title = parts[0]
        dynasty_label = ""
        author_label = ""
    return title, dynasty_label, author_label


def iter_books(data_dir: Path) -> list[Book]:
    books: list[Book] = []
    for path in sorted(data_dir.rglob("*.txt")):
        book = parse_filename(path.name)
        if not book:
            continue
        books.append(
            Book(
                **{**book.__dict__, "path": str(path.relative_to(data_dir))},
            )
        )
    books.sort(key=lambda item: (item.work_id, item.path))
    return books


def normalize_author_name(author_label: str) -> str | None:
    name = author_label.strip()
    if not name:
        return None
    name = PAREN_RE.sub("", name).strip()
    if not name:
        return None
    if any(marker in name for marker in UNKNOWN_AUTHOR_MARKERS):
        return None
    return name


def parse_kr_catalog(kr_catalog_dir: Path) -> dict[str, list[PersonEvidence]]:
    evidence_by_work: dict[str, list[PersonEvidence]] = {}
    kr_dir = kr_catalog_dir / "KR"
    if not kr_dir.exists():
        return evidence_by_work
    for path in sorted(kr_dir.glob("KR*.txt")):
        _parse_kr_catalog_file(path, evidence_by_work)
    return evidence_by_work


def _parse_kr_catalog_file(
    path: Path, evidence_by_work: dict[str, list[PersonEvidence]]
) -> None:
    current_work_id: str | None = None
    in_people_section = False
    current_person: str | None = None
    current_props: dict[str, str] = {}

    def flush_person() -> None:
        nonlocal current_person, current_props
        if not current_work_id or not current_person:
            current_person = None
            current_props = {}
            return
        raw_dates = current_props.get("DATES", "").strip()
        if not raw_dates:
            current_person = None
            current_props = {}
            return
        date_not_before, date_not_after = parse_dates(raw_dates)
        if date_not_before is None and date_not_after is None:
            current_person = None
            current_props = {}
            return
        evidence_by_work.setdefault(current_work_id, []).append(
            PersonEvidence(
                work_id=current_work_id,
                person_name=current_person,
                function=current_props.get("FUNCTION", "").strip(),
                dynasty_label=current_props.get("DYNASTY", "").strip(),
                raw_dates=raw_dates,
                date_not_before=date_not_before,
                date_not_after=date_not_after,
            )
        )
        current_person = None
        current_props = {}

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            work_match = WORK_RE.match(line)
            if work_match:
                flush_person()
                current_work_id = work_match.group(1)
                in_people_section = False
                continue

            if PEOPLE_SECTION_RE.match(line):
                flush_person()
                in_people_section = True
                continue

            if HEADING4_RE.match(line) and not PEOPLE_SECTION_RE.match(line):
                if in_people_section:
                    flush_person()
                in_people_section = False
                continue

            if in_people_section:
                person_match = PERSON_RE.match(line)
                if person_match:
                    flush_person()
                    current_person = person_match.group(1).strip()
                    continue

                prop_match = PROPERTY_RE.match(line)
                if prop_match and current_person:
                    key, value = prop_match.groups()
                    current_props[key] = value.strip()

    flush_person()


def parse_dates(raw: str) -> tuple[int | None, int | None]:
    normalized = raw.strip().lower()
    numbers = [int(value) for value in DATE_NUMBER_RE.findall(raw)]
    if not numbers:
        return None, None
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    value = numbers[0]
    if normalized.startswith("d.") or normalized.startswith("d "):
        return None, value
    if normalized.startswith("b.") or normalized.startswith("b "):
        return value, None
    if normalized.startswith("fl."):
        return value, value
    return value, value


def load_cbdb_people(
    mdb_path: Path,
    author_names: set[str],
    mdb_export: str | None = None,
) -> dict[str, list[CBDBPerson]]:
    if not mdb_path.exists() or not author_names:
        return {}
    export_cmd = mdb_export or shutil.which("mdb-export") or "/usr/local/bin/mdb-export"
    cmd = [export_cmd, str(mdb_path), "ZZZ_BIOG_MAIN"]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    reader = csv.reader(process.stdout)
    header = next(reader, None)
    if not header:
        process.wait()
        return {}
    idx_name = header.index("c_name_chn")
    idx_person = header.index("c_personid")
    idx_birth = header.index("c_birthyear")
    idx_death = header.index("c_deathyear")
    idx_fl_earliest = header.index("c_fl_earliest_year")
    idx_fl_latest = header.index("c_fl_latest_year")

    people_by_name: dict[str, list[CBDBPerson]] = {}
    for row in reader:
        if len(row) <= idx_name:
            continue
        name = row[idx_name].strip()
        if not name or name not in author_names:
            continue
        birth = parse_year(row[idx_birth] if len(row) > idx_birth else "")
        death = parse_year(row[idx_death] if len(row) > idx_death else "")
        fl_earliest = parse_year(
            row[idx_fl_earliest] if len(row) > idx_fl_earliest else ""
        )
        fl_latest = parse_year(
            row[idx_fl_latest] if len(row) > idx_fl_latest else ""
        )
        if not any([birth, death, fl_earliest, fl_latest]):
            continue
        people_by_name.setdefault(name, []).append(
            CBDBPerson(
                person_id=row[idx_person].strip(),
                name=name,
                birth_year=birth,
                death_year=death,
                fl_earliest=fl_earliest,
                fl_latest=fl_latest,
            )
        )
    process.wait()
    return people_by_name


def parse_year(value: str) -> int | None:
    cleaned = value.strip()
    if not cleaned or cleaned == "0":
        return None
    try:
        year = int(cleaned)
    except ValueError:
        return None
    if year == 0:
        return None
    return year


def load_dynasty_ranges(path: Path | None) -> dict[str, tuple[int, int]]:
    if not path or not path.exists():
        return dict(DEFAULT_DYNASTY_RANGES)
    ranges: dict[str, tuple[int, int]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            label = (row.get("dynasty_label") or "").strip()
            start = (row.get("date_not_before") or "").strip()
            end = (row.get("date_not_after") or "").strip()
            if not label or not start or not end:
                continue
            ranges[label] = (int(start), int(end))
    return ranges


def resolve_dynasty_range(
    dynasty_label: str, ranges: dict[str, tuple[int, int]]
) -> tuple[int | None, int | None, str]:
    if not dynasty_label:
        return None, None, "missing dynasty label"
    normalized = DYNASTY_ALIASES.get(dynasty_label, dynasty_label)
    match = ranges.get(normalized)
    if not match:
        return None, None, f"unmapped dynasty label={dynasty_label}"
    date_not_before, date_not_after = match
    if normalized != dynasty_label:
        return (
            date_not_before,
            date_not_after,
            f"dynasty_label={dynasty_label} alias={normalized}",
        )
    return date_not_before, date_not_after, f"dynasty_label={dynasty_label}"


def choose_best_evidence(evidence: list[PersonEvidence]) -> PersonEvidence | None:
    best: PersonEvidence | None = None
    best_score = -1
    for item in evidence:
        score = 0
        if item.date_not_before is not None and item.date_not_after is not None:
            score += 2
        elif item.date_not_before is not None or item.date_not_after is not None:
            score += 1
        if item.function in PREFERRED_FUNCTIONS:
            score += 1
        if score > best_score:
            best = item
            best_score = score
    return best


def choose_cbdb_person(candidates: list[CBDBPerson]) -> CBDBPerson | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return None


def cbdb_date_range(person: CBDBPerson) -> tuple[int | None, int | None, str]:
    if person.birth_year is not None and person.death_year is not None:
        return person.birth_year, person.death_year, "author_lifespan_bound"
    if person.fl_earliest is not None and person.fl_latest is not None:
        return person.fl_earliest, person.fl_latest, "floruit_bound"
    return None, None, ""


def write_books_csv(path: Path, books: list[Book]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "collection",
                "work_id",
                "title",
                "dynasty_label",
                "author_label",
                "filename",
                "path",
            ],
        )
        writer.writeheader()
        for book in books:
            writer.writerow(
                {
                    "collection": book.collection,
                    "work_id": book.work_id,
                    "title": book.title,
                    "dynasty_label": book.dynasty_label,
                    "author_label": book.author_label,
                    "filename": book.filename,
                    "path": book.path,
                }
            )


def write_publication_date_ranges(
    path: Path,
    books: list[Book],
    ranges: dict[str, tuple[int, int]],
    kr_evidence: dict[str, list[PersonEvidence]],
    cbdb_people: dict[str, list[CBDBPerson]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "work_id",
                "source",
                "date_not_before",
                "date_not_after",
                "date_type",
                "confidence",
                "note",
                "ref",
            ],
        )
        writer.writeheader()
        for book in books:
            author_name = normalize_author_name(book.author_label)
            if author_name:
                cbdb_candidates = cbdb_people.get(author_name, [])
                cbdb_person = choose_cbdb_person(cbdb_candidates)
                if cbdb_person:
                    date_not_before, date_not_after, date_type = cbdb_date_range(
                        cbdb_person
                    )
                    if date_not_before is not None and date_not_after is not None:
                        writer.writerow(
                            {
                                "work_id": book.work_id,
                                "source": "cbdb",
                                "date_not_before": date_not_before,
                                "date_not_after": date_not_after,
                                "date_type": date_type,
                                "confidence": "medium",
                                "note": f"name={cbdb_person.name} id={cbdb_person.person_id}",
                                "ref": "CBDB_20240208_DATA2",
                            }
                        )
                        continue

            evidence = kr_evidence.get(book.work_id, [])
            best = choose_best_evidence(evidence) if evidence else None
            if best:
                confidence = "medium"
                if best.date_not_before is None or best.date_not_after is None:
                    confidence = "low"
                writer.writerow(
                    {
                        "work_id": book.work_id,
                        "source": "kr_catalog",
                        "date_not_before": ""
                        if best.date_not_before is None
                        else best.date_not_before,
                        "date_not_after": ""
                        if best.date_not_after is None
                        else best.date_not_after,
                        "date_type": "author_lifespan_bound",
                        "confidence": confidence,
                        "note": (
                            f"person={best.person_name} "
                            f"function={best.function} "
                            f"dates={best.raw_dates}"
                        ),
                        "ref": "KR-Catalog",
                    }
                )
                continue

            date_not_before, date_not_after, note = resolve_dynasty_range(
                book.dynasty_label, ranges
            )
            writer.writerow(
                {
                    "work_id": book.work_id,
                    "source": "filename_dynasty",
                    "date_not_before": "" if date_not_before is None else date_not_before,
                    "date_not_after": "" if date_not_after is None else date_not_after,
                    "date_type": "dynasty_bound",
                    "confidence": "low",
                    "note": note,
                    "ref": "",
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan kr-shadow data to list books and date ranges."
    )
    parser.add_argument("--data-dir", default="data", help="Root data directory.")
    parser.add_argument(
        "--books-csv",
        default="data/books.csv",
        help="Output CSV for book listing.",
    )
    parser.add_argument(
        "--date-ranges-csv",
        default="data/publication_date_range.csv",
        help="Output CSV for publication date ranges.",
    )
    parser.add_argument(
        "--dynasty-ranges",
        default="",
        help="Optional CSV mapping dynasty_label to date ranges.",
    )
    parser.add_argument(
        "--kr-catalog-dir",
        default="data/sources/KR-Catalog",
        help="Path to KR-Catalog checkout for author dates.",
    )
    parser.add_argument(
        "--cbdb-mdb",
        default="",
        help="Path to CBDB DATA2 .mdb for author lifespan ranges.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    books = iter_books(data_dir)
    write_books_csv(Path(args.books_csv), books)

    ranges_path = Path(args.dynasty_ranges) if args.dynasty_ranges else None
    ranges = load_dynasty_ranges(ranges_path)
    kr_catalog_dir = Path(args.kr_catalog_dir)
    kr_evidence = parse_kr_catalog(kr_catalog_dir)
    cbdb_mdb = Path(args.cbdb_mdb) if args.cbdb_mdb else None
    cbdb_people: dict[str, list[CBDBPerson]] = {}
    if cbdb_mdb:
        author_names = {
            name
            for name in (normalize_author_name(book.author_label) for book in books)
            if name
        }
        cbdb_people = load_cbdb_people(cbdb_mdb, author_names)
    write_publication_date_ranges(
        Path(args.date_ranges_csv), books, ranges, kr_evidence, cbdb_people
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
