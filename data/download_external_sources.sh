#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${KRATT_SOURCES_DIR:-$ROOT_DIR/data/sources/external}"

mkdir -p "$DEST_DIR"

download() {
  local url="$1"
  local out="$2"
  if [[ -s "$out" ]]; then
    echo "skip: $out"
    return 0
  fi
  echo "downloading: $out"
  curl -L --fail --retry 3 --retry-delay 2 --retry-connrefused -o "$out" "$url"
}

download "https://researchdata.ntu.edu.sg/api/access/datafile/:persistentId?persistentId=doi:10.21979/N9/REE4MJ/JHGS7Z" \
  "$DEST_DIR/Buddhist.zip"
download "https://researchdata.ntu.edu.sg/api/access/datafile/:persistentId?persistentId=doi:10.21979/N9/REE4MJ/MZFZ85" \
  "$DEST_DIR/Daoist_Canon_Metadata_All_in_Rows_edited_20181103.xlsx"
download "https://researchdata.ntu.edu.sg/api/access/datafile/21089" \
  "$DEST_DIR/Daoist_Canon_Metadata_All_in_Rows_edited_20190731_RewriteHeaders.xlsx"
download "https://researchdata.ntu.edu.sg/api/access/datafile/:persistentId?persistentId=doi:10.21979/N9/REE4MJ/TICP2X" \
  "$DEST_DIR/Meta.Data.Buddhist5_20181102.xlsx"
download "https://researchdata.ntu.edu.sg/api/access/datafile/:persistentId?persistentId=doi:10.21979/N9/BWLRQJ/G3RRG4" \
  "$DEST_DIR/Kanripo.Daoist.Index_KR5.txt"
download "https://download.ctext.org/ctext_datawiki-2025-05-19.ttl.zip" \
  "$DEST_DIR/ctext_datawiki-2025-05-19.ttl.zip"
download "https://authority.dila.edu.tw/downloads/authority_person.2026-01.zip" \
  "$DEST_DIR/authority_person.2026-01.zip"
download "https://authority.dila.edu.tw/downloads/authority_person_rdf.2020-12.rdf" \
  "$DEST_DIR/authority_person_rdf.2020-12.rdf"
download "https://authority.dila.edu.tw/downloads/authority_place.2026-01.zip" \
  "$DEST_DIR/authority_place.2026-01.zip"
download "https://authority.dila.edu.tw/downloads/authority_place_rdf.2020-12.rdf" \
  "$DEST_DIR/authority_place_rdf.2020-12.rdf"
download "https://authority.dila.edu.tw/downloads/authority_time.2012-02.zip" \
  "$DEST_DIR/authority_time.2012-02.zip"
download "https://authority.dila.edu.tw/downloads/authority_time_chinese.2012-02.zip" \
  "$DEST_DIR/authority_time_chinese.2012-02.zip"
download "https://authority.dila.edu.tw/downloads/authority_time_japanese.2012-02.zip" \
  "$DEST_DIR/authority_time_japanese.2012-02.zip"
download "https://authority.dila.edu.tw/downloads/authority_time_korean.2012-02.zip" \
  "$DEST_DIR/authority_time_korean.2012-02.zip"
download "https://github.com/DILA-edu/Authority-Databases/archive/refs/heads/master.zip" \
  "$DEST_DIR/DILA-Authority-Databases-master.zip"
download "https://huggingface.co/datasets/cbdb/cbdb-sqlite/resolve/main/latest.7z?download=true" \
  "$DEST_DIR/cbdb_latest.7z"
download "https://raw.githubusercontent.com/cbdb-project/cbdb_sqlite/master/latest.7z" \
  "$DEST_DIR/cbdb_latest_from_github.7z"

echo "done"
