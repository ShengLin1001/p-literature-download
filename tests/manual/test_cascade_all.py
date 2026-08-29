#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run scansci-pdf get on all 22 test DOIs and record results.
This tests the full cascade (API, OA, browser, etc.) without manual intervention."""
import subprocess
import sys
import time
import json
from pathlib import Path

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT = Path("F:/BaiduSyncdisk/version20240608/main_code_space/scansci-pdf/mytest/cascade_test_downloads")
OUT.mkdir(parents=True, exist_ok=True)

# Read test DOIs
dois = []
with open("F:/BaiduSyncdisk/version20240608/main_code_space/scansci-pdf/mytest/test-doi.txt", encoding="utf-8-sig") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Extract DOI (first column, tab-separated)
        doi = line.split("\t")[0].split(" | ")[0].split(None, 1)[0] if "\t" not in line else line.split("\t")[0]
        if " | " in doi:
            doi = doi.split(" | ")[0]
        dois.append(doi.strip())

print(f"Testing {len(dois)} DOIs\n")

results = []
for i, doi in enumerate(dois, 1):
    print(f"\n{'='*60}")
    print(f"[{i}/{len(dois)}] {doi}")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        proc = subprocess.run(
            ["scansci-pdf", "get", doi, "--output", str(OUT)],
            capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace"
        )
        elapsed = time.time() - t0
        output = proc.stdout + proc.stderr

        # Check if PDF was downloaded
        pdf_files = list(OUT.glob("*" + doi.split("/")[-1].replace(".", "_") + "*.pdf")) + \
                    list(OUT.glob("*" + doi.replace("/", "_") + "*.pdf"))

        # Also check for any new PDFs created in the last 30s
        new_pdfs = [f for f in OUT.glob("*.pdf") if f.stat().st_mtime > t0 - 5]

        success = "OK:" in output and proc.returncode == 0
        source = "unknown"
        if success:
            for line in output.split("\n"):
                if "Source:" in line:
                    source = line.split("Source:")[-1].strip()
                    break

        result = {
            "doi": doi,
            "success": success,
            "source": source,
            "elapsed": round(elapsed, 1),
            "pdf_files": [str(f.name) for f in new_pdfs],
            "returncode": proc.returncode,
        }
        print(f"  Result: {'SUCCESS' if success else 'FAILED'} (source={source}, {elapsed:.1f}s)")
        if new_pdfs:
            print(f"  PDF: {new_pdfs[0].name} ({new_pdfs[0].stat().st_size} bytes)")
        else:
            print(f"  No PDF found")
            # Print last few lines of output for debugging
            lines = output.strip().split("\n")
            for line in lines[-5:]:
                print(f"  {line}")
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        result = {"doi": doi, "success": False, "source": "timeout", "elapsed": round(elapsed, 1)}
        print(f"  TIMEOUT after {elapsed:.1f}s")
    except Exception as e:
        result = {"doi": doi, "success": False, "source": "error", "error": str(e)}
        print(f"  ERROR: {e}")

    results.append(result)
    # Save intermediate results
    with open(OUT / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    time.sleep(2)

# Final summary
print(f"\n\n{'='*60}")
print("FINAL SUMMARY")
print(f"{'='*60}")
for r in results:
    status = "OK" if r["success"] else "FAIL"
    print(f"  {status:4s} {r['doi'][:45]:47s} {r.get('source', 'unknown'):20s} {r.get('elapsed', 0)}s")
ok = sum(1 for r in results if r["success"])
print(f"\n  Success: {ok}/{len(results)} ({100*ok//len(results)}%)")

# Save final results
with open(OUT / "results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nResults saved to {OUT / 'results.json'}")
