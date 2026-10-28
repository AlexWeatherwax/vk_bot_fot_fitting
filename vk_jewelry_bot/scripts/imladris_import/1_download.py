import json
import re
import unicodedata
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests

HERE = Path(__file__).parent
RAW_DIR = HERE / "raw"

TRANSLIT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i',
    'й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
    'у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'',
    'э':'e','ю':'yu','я':'ya',
}

def slugify(text: str) -> str:
    text = text.lower().replace('"', '').replace('«','').replace('»','')
    out = []
    for ch in text:
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        else:
            out.append('-')
    slug = re.sub(r'-+', '-', ''.join(out)).strip('-')
    return slug or "item"

def main():
    entries = []
    with open(HERE / "products.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    # de-dup slugs per category
    seen_slugs = {}
    tasks = []
    for i, e in enumerate(entries):
        cat_dir = RAW_DIR / e["category"]
        cat_dir.mkdir(parents=True, exist_ok=True)
        base_slug = slugify(e["title"])
        key = (e["category"], base_slug)
        n = seen_slugs.get(key, 0)
        seen_slugs[key] = n + 1
        slug = base_slug if n == 0 else f"{base_slug}-{n+1}"
        dest = cat_dir / f"{slug}.jpg"
        tasks.append((e, dest))

    def download(task):
        entry, dest = task
        try:
            r = requests.get(entry["url"], timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            dest.write_bytes(r.content)
            return (dest.name, len(r.content), None)
        except Exception as exc:
            return (dest.name, 0, str(exc))

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(download, tasks):
            results.append(res)

    ok = [r for r in results if r[2] is None]
    failed = [r for r in results if r[2] is not None]
    print(f"OK: {len(ok)}, FAILED: {len(failed)}")
    for name, size, err in failed:
        print("FAILED:", name, err)

    # write manifest mapping for next step
    manifest = []
    for (entry, dest) in tasks:
        manifest.append({
            "category": entry["category"],
            "title": entry["title"],
            "raw_path": str(dest.relative_to(HERE)),
        })
    (HERE / "raw_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

if __name__ == "__main__":
    main()
