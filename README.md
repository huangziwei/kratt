# kratt

An attempt to attest earliest usage of Chinese words using [KR-Shadow](https://github.com/kr-shadow) corpus.

The biggest obstable right now is still getting the reliable sources for the range of publication date.

## Usage

```bash
uv sync
git submodule update --init --recursive

kratt 现在
kratt 现在 -n 20 --context 40
kratt 现在 --no-dedup
```
