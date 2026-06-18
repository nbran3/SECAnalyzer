import os
import re
from glob import glob
from pathlib import Path
from azure.identity import ClientSecretCredential
from azure.storage.blob import BlobServiceClient

companies = [
    "Apple Inc.",
    "Microsoft Corp",
    "Amazon.com Inc",
    "Alphabet Inc. (Google)",
    "Meta Platforms Inc",
    "Tesla Inc",
    "NVIDIA Corp",
    "Walmart Inc",
    "JPMorgan Chase & Co",
    "Walt Disney Co",
    "Coca-Cola Co",
]

# Build a lookup: "Apple_Inc." → "Apple Inc." so we can match filenames fast
_slug_to_name = {c.replace(" ", "_"): c for c in companies}


def _company_for_file(file_path: str) -> str | None:
    """Return the company name whose slug appears in file_path, or None."""
    basename = os.path.basename(file_path)
    for slug, name in _slug_to_name.items():
        if slug in basename:
            return name
    return None


def parse_local_10k_file(file_path: str) -> dict | None:
    """
    Read a local SEC 10-K .htm file, clean it, and return LLM-ready Markdown.
    Returns None if the file doesn't belong to a company in the target list.
    """
    company = _company_for_file(file_path)
    if not company:
        print(f"Skipping {os.path.basename(file_path)} — not in target company list.")
        return None

    print(f"Parsing: {os.path.basename(file_path)}  ({company})")

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f, "html.parser")

    doc_title = soup.title.string if soup.title else os.path.basename(file_path)

    for tag in soup(["script", "style", "meta", "link", "noscript", "head"]):
        tag.extract()

    for table in soup.find_all("table"):
        for attr in ["style", "cellpadding", "cellspacing", "width", "bgcolor"]:
            if table.has_attr(attr):
                del table[attr]

    print("  Converting HTML to Markdown…")
    markdown_content = md(
        str(soup),
        strip=["a", "img", "span"],
        heading_style="ATX",
    )

    markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)
    markdown_content = re.sub(r" {2,}", " ", markdown_content)

    return {
        "metadata": {
            "company": company,
            "source_file": os.path.basename(file_path),
            "document_title": doc_title,
        },
        "cleaned_content": markdown_content.strip(),
    }


def process_all_filings(directory: str = ".") -> list[dict]:
    """
    Discover every *_10k_latest.htm file in `directory`, parse each one,
    save the cleaned Markdown to a sibling *_llm_ready.txt file, and
    return the list of result dicts.
    """
    pattern = os.path.join(directory, "*_10k_latest.htm")
    htm_files = sorted(glob(pattern))

    if not htm_files:
        print(f"No *_10k_latest.htm files found in '{directory}'.")
        return []

    results = []
    for path in htm_files:
        result = parse_local_10k_file(path)
        if result is None:
            continue

        out_path = Path(path).with_name(
            Path(path).stem + "_llm_ready.txt"
        )
        out_path.write_text(result["cleaned_content"], encoding="utf-8")
        print(f"  Saved → {out_path.name}\n")
        results.append(result)

    print(f"Done. Processed {len(results)}/{len(htm_files)} files.")
    return results


if __name__ == "__main__":
    process_all_filings(".")
