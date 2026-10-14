#!/usr/bin/env python
"""Fetch the open-access PhysioNet corpora used by rhythm_head.py. Nothing is committed.

    python -I fetch_data.py --data DATA_DIR [--only cinc2017 afdb mitdb nstdb] [--dry-run]

Each corpus goes into its own directory under DATA_DIR (treat downloads as
untrusted data). Files are verified against the project's SHA256SUMS.txt by
EXACT path; only root-level files are taken (AFDB also ships an old/ copy of
every .atr that must not be mixed in). physionet.org can be very slow, so the
S3 open-data mirror run by PhysioNet is used where it exists; NSTDB is not on
the mirror, so its three noise-only records come from physionet.org.

Licences: all four corpora are open access (Open Data Commons Attribution 1.0).
Cite: CinC 2017 doi:10.13026/d3hm-sf11, AFDB doi:10.13026/C2MW2D,
MITDB doi:10.13026/C2F305, NSTDB doi:10.13026/C2HS3T.
"""
import argparse, hashlib, pathlib, sys, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET, zipfile
from concurrent.futures import ThreadPoolExecutor

# SHA-256 of training2017.zip, computed from the copy the spike results were produced with
# (99,226,822 bytes). The challenge project publishes no SHA256SUMS, so this is a pin, not
# a vendor checksum: cross-check it against physionet.org once if that matters to you.
PINNED = {
    "cinc2017/training2017.zip": "25fdbab36bb6724b66a4d2c26ff89f6b9d6ff87e6aed714d24cf5bf071cd1255",
}

S3 = "https://physionet-open.s3.amazonaws.com/"
PN = "https://physionet.org/files/"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
KEEP = (".dat", ".hea", ".atr")
EXTRA = ("RECORDS", "ANNOTATORS", "LICENSE.txt", "SHA256SUMS.txt")


def s3_keys(prefix):
    keys, token = [], None
    while True:
        url = S3 + "?list-type=2&prefix=" + urllib.parse.quote(prefix)
        if token:
            url += "&continuation-token=" + urllib.parse.quote(token)
        root = ET.fromstring(urllib.request.urlopen(url, timeout=60).read())
        keys += [(c.find("s:Key", NS).text, int(c.find("s:Size", NS).text)) for c in root.findall("s:Contents", NS)]
        t = root.find("s:NextContinuationToken", NS)
        token = t.text if t is not None else None
        if not token:
            return keys


def get(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            tmp.rename(dest)
            return dest.stat().st_size
        except Exception as e:  # retry transient errors
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def plan(data, only):
    jobs = []  # (url, dest, size or None)
    if "cinc2017" in only:
        d = data / "cinc2017"
        jobs += [(S3 + "challenge-2017/1.0.0/training2017.zip", d / "training2017.zip", None),
                 (S3 + "challenge-2017/1.0.0/REFERENCE-v3.csv", d / "extracted" / "REFERENCE-v3.csv", None)]
    for ds in ("afdb", "mitdb"):
        if ds in only:
            base = f"{ds}/1.0.0/"
            for key, size in s3_keys(base):
                name = key[len(base):]
                if "/" in name:            # skip old/ and any other subfolder
                    continue
                if name.endswith(KEEP) or name in EXTRA:
                    jobs.append((S3 + key, data / ds / "extracted" / name, size))
    if "nstdb" in only:
        for n in ("bw", "em", "ma"):
            for ext in (".hea", ".dat"):
                jobs.append((f"{PN}nstdb/1.0.0/{n}{ext}", data / "nstdb" / "extracted" / f"{n}{ext}", None))
        for n in ("SHA256SUMS.txt", "RECORDS"):
            jobs.append((f"{PN}nstdb/1.0.0/{n}", data / "nstdb" / "extracted" / n, None))
    return jobs


def verify(data, ds):
    root = data / ds / "extracted"
    sums = {}
    for line in (root / "SHA256SUMS.txt").read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1]] = parts[0]          # exact relative path
    bad = ok = 0
    unlisted = []
    for p in sorted(root.iterdir()):
        if p.name == "SHA256SUMS.txt" or p.name.endswith(".part"):
            continue
        want = sums.get(p.name)
        if want is None:
            unlisted.append(p.name)            # downloaded but not covered by the sums file
            continue
        if hashlib.sha256(p.read_bytes()).hexdigest() == want:
            ok += 1
        else:
            bad += 1
            print("CHECKSUM MISMATCH", ds, p.name)
    # Signal files must be covered; small text extras (RECORDS, LICENSE.txt...) only warn.
    data_unlisted = [n for n in unlisted if n.endswith(KEEP)]
    if unlisted:
        print(f"{ds}: NOT IN SHA256SUMS.txt: {unlisted}")
    print(f"{ds}: {ok} files verified, {bad} mismatches, {len(unlisted)} unlisted")
    return bad == 0 and not data_unlisted


def extract_cinc(data):
    z = data / "cinc2017" / "training2017.zip"
    out = data / "cinc2017" / "extracted"
    got = hashlib.sha256(z.read_bytes()).hexdigest()
    if got != PINNED["cinc2017/training2017.zip"]:
        sys.exit(f"training2017.zip sha256 mismatch: {got}")
    with zipfile.ZipFile(z) as zf:
        bad = [n for n in zf.namelist() if n.startswith("/") or ".." in pathlib.PurePosixPath(n).parts]
        if bad or zf.testzip() is not None:
            sys.exit(f"unsafe or corrupt zip: {bad[:3]}")
        zf.extractall(out)
    print("cinc2017: extracted", z.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--only", nargs="*", default=["cinc2017", "afdb", "mitdb", "nstdb"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    data = pathlib.Path(a.data)
    jobs = plan(data, set(a.only))
    known = sum(s or 0 for _, _, s in jobs)
    print(f"{len(jobs)} files; known size {known/1e6:.0f} MB (zip and a few files unlisted)")
    if a.dry_run:
        return
    with ThreadPoolExecutor(max_workers=8) as ex:
        for _ in ex.map(lambda j: get(j[0], j[1]), jobs):
            pass
    if "cinc2017" in a.only:
        extract_cinc(data)
    ok = all(verify(data, ds) for ds in a.only if ds != "cinc2017")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
