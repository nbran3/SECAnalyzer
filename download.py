import requests
import time
import json

# SEC requires a descriptive User-Agent identifying you — NOT an API key, NOT a login.
# Format: "Your Name your.email@example.com"
HEADERS = {
    "User-Agent": "Noah Brannon nbwan3@gmail.com"
}

# Step 1: Get Company's filing history
COMPANY_CIKS = {
    "Apple Inc.":                  "0000320193",
    "Microsoft Corp":              "0000789019",
    "Amazon.com Inc":              "0001018724",
    "Alphabet Inc. (Google)":      "0001652044",
    "Meta Platforms Inc":          "0001326801",
    "Tesla Inc":                   "0001318605",
    "NVIDIA Corp":                 "0001045810",
    "Walmart Inc":                 "0000104169",
    "JPMorgan Chase & Co":         "0000019617",
    "Walt Disney Co":              "0001744489",
    "Coca-Cola Co":                "0000021344",
}


def get_company_filings(cik: str, headers=HEADERS) -> dict:
    for company, cik in COMPANY_CIKS.items():
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"

        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        print("Company:", data["name"])
        print("Total recent filings:", len(data["filings"]["recent"]["form"]))

        # Step 2: Filter for 10-K (annual report) filings only
        recent = data["filings"]["recent"]
        forms = recent["form"]
        accession_numbers = recent["accessionNumber"]
        primary_docs = recent["primaryDocument"]
        filing_dates = recent["filingDate"]

        ten_ks = []
        for i, form in enumerate(forms):
            if form == "10-K":
                ten_ks.append({
                "date": filing_dates[i],
                "accession": accession_numbers[i],
                "doc": primary_docs[i]
        })

        print(f"\nFound {len(ten_ks)} 10-K filings")

        # Step 3: Build the actual document URL for the most recent 10-K
        if ten_ks:
            latest = ten_ks[0]
            acc_no_dashes = latest["accession"].replace("-", "")
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_no_dashes}/{latest['doc']}"
            print("\nMost recent 10-K URL:")
            print(doc_url)

        # Step 4: Download it (be polite — SEC asks for max 10 requests/sec)
        time.sleep(0.2)
        doc_resp = requests.get(doc_url, headers=headers)
        print(f"\nDownload status: {doc_resp.status_code}")
        print(f"Document size: {len(doc_resp.content)} bytes")

        with open(f"{company.replace(' ', '_')}_10k_latest.htm", "wb") as f:
            f.write(doc_resp.content)
        print(f"Saved to {company.replace(' ', '_')}_10k_latest.htm")

