import json
import os
import re
from pathlib import Path
from typing import Optional
import pandas as pd
from azure.identity import ClientSecretCredential
from azure.storage.blob import BlobServiceClient
import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator


load_dotenv()

EXTRACTION_SYSTEM_PROMPT = """You are a financial document extraction system.
You will be given the text of a company's 10-K filing (or an excerpt of it).

Extract the following into the EXACT JSON schema below. Do not include any
text before or after the JSON. Do not use markdown code fences.

Rules:
- Only extract information explicitly stated in the document. Never infer
  or fill in numbers from general knowledge of the company.
- For risk factors, preserve SPECIFIC details (named countries, named
  technologies, dates, percentages) rather than generalizing them away.
  Example: write "manufacturing concentrated in China, India, Japan, South
  Korea, Taiwan, and Vietnam" NOT "manufacturing concentrated in Asia."
- If a financial figure is not present in the provided text, return null
  for that field rather than guessing.
- If you are uncertain about the accuracy of any extracted field, add its
  name to "low_confidence_fields".
- Group each risk factor sentence into exactly one category. Use concise
  single-sentence bullets, not full paragraphs.
- Include at most 3 bullets per risk category. Prioritize the most
  material or specific risks; omit minor or generic ones.

Return JSON matching this exact schema:
{
  "company_name": string,
  "fiscal_year": integer,
  "total_revenue": number or null,
  "net_income": number or null,
  "risk_factors": {
    "economic_risks": [string],
    "geopolitical_risks": [string],
    "operational_risks": [string],
    "competitive_risks": [string],
    "product_risks": [string],
    "supply_chain_risks": [string],
    "intellectual_property_risks": [string],
    "ecosystem_risks": [string],
    "talent_risks": [string]
  },
  "low_confidence_fields": [string]
}
"""


# ---------------------------------------------------------------------------
# Pydantic schema — Silver layer gate
# ---------------------------------------------------------------------------

class RiskFactors(BaseModel):
    economic_risks: list[str] = []
    geopolitical_risks: list[str] = []
    operational_risks: list[str] = []
    competitive_risks: list[str] = []
    product_risks: list[str] = []
    supply_chain_risks: list[str] = []
    intellectual_property_risks: list[str] = []
    ecosystem_risks: list[str] = []
    talent_risks: list[str] = []


class TenKExtraction(BaseModel):
    company_name: str
    fiscal_year: int
    total_revenue: Optional[float] = None
    net_income: Optional[float] = None
    risk_factors: RiskFactors
    low_confidence_fields: list[str] = []

    @field_validator("fiscal_year")
    @classmethod
    def validate_fiscal_year(cls, v: int) -> int:
        if not 2000 <= v <= 2026:
            raise ValueError(f"fiscal_year {v} is outside the valid range 2000–2026")
        return v

    @field_validator("total_revenue", "net_income", mode="before")
    @classmethod
    def validate_positive(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Revenue and net income values must be positive numbers")
        return v


# ---------------------------------------------------------------------------
# Section extraction helpers
# ---------------------------------------------------------------------------

def _extract_section(text: str, start_pattern: str, end_pattern: str) -> str:
    """Return the text slice that starts at start_pattern and ends just before end_pattern."""
    start = re.search(start_pattern, text, re.IGNORECASE | re.MULTILINE)
    if not start:
        return ""
    tail = text[start.start():]
    end = re.search(end_pattern, tail[1:], re.IGNORECASE | re.MULTILINE)
    return tail[: end.start() + 1] if end else tail


def _build_context(text: str) -> str:
    """
    Carve out the three sections the model needs rather than sending the
    entire document:
      1. Filing header  — company name + fiscal year
      2. Financial summary — total revenue + net income
      3. Risk Factors section — the main payload
    """
    parts: list[str] = []

    # 1. Filing header
    header_match = re.search(
        r"UNITED STATES\s+SECURITIES AND EXCHANGE COMMISSION", text, re.IGNORECASE
    )
    if header_match:
        snippet = text[header_match.start(): header_match.start() + 3_000]
        parts.append("=== FILING HEADER ===\n" + snippet)

    # 2. Financial highlights — income statement or MD&A results section
    fin = _extract_section(
        text,
        r"(?:CONSOLIDATED STATEMENTS?\s+OF OPERATIONS|Results of Operations|Total net sales)",
        r"(?:CONSOLIDATED BALANCE SHEETS?|Liquidity and Capital|NOTES TO CONSOLIDATED)",
    )
    if fin:
        parts.append("=== FINANCIAL SUMMARY ===\n" + fin[:6_000])

    # 3. Risk Factors (Item 1A → Item 1B)
    risks = _extract_section(
        text,
        r"Item\s+1A\.?\s+Risk Factors",
        r"Item\s+1B\.",
    )
    if risks:
        parts.append("=== RISK FACTORS ===\n" + risks)

    if not parts:
        raise ValueError("Could not locate any usable sections in the provided file.")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _run_extraction(document_context: str) -> dict:
    """Call Haiku, parse JSON, and validate against the Pydantic schema."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": document_context}],
    )

    raw_text = response.content[0].text.strip()
    raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.DOTALL).strip()

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Model returned invalid JSON: {exc}\n\n"
            f"Raw output (first 500 chars):\n{raw_text[:500]}"
        ) from exc

    try:
        validated = TenKExtraction(**raw_data)
    except Exception as exc:
        raise ValueError(f"Silver layer schema validation failed: {exc}") from exc

    result = validated.model_dump()

    if result["low_confidence_fields"]:
        print(
            f"⚠️  Record flagged for manual review. "
            f"Low-confidence fields: {result['low_confidence_fields']}"
        )

    return result


def download_blob_text(blob_name: str) -> str:
    """
    Download a blob from Azure Blob Storage and return its contents as a string.

    Reads credentials from the environment (via .env):
        AzureBlobContainerName, AzureAccountUrl,
        AzureTenantId, AzureClientId, AzureClientSecret
    """
    credential = ClientSecretCredential(
        tenant_id=os.getenv("AzureTenantId"),
        client_id=os.getenv("AzureClientId"),
        client_secret=os.getenv("AzureClientSecret"),
    )
    blob_service_client = BlobServiceClient(
        account_url=os.getenv("AzureAccountUrl"),
        credential=credential,
    )
    blob_client = blob_service_client.get_blob_client(
        container=os.getenv("AzureBlobContainerName"),
        blob=blob_name,
    )
    return blob_client.download_blob().readall().decode("utf-8")


def extract_10k(file_path: str) -> dict:
    """Extract structured data from a local LLM-ready .txt file."""
    text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    return _run_extraction(_build_context(text))


def extract_10k_from_blob(blob_name: str) -> dict:
    """Download a blob from Azure and extract structured 10-K data from it."""
    text = download_blob_text(blob_name)
    return _run_extraction(_build_context(text))


def _company_to_blob_name(company: str) -> str:
    return company.replace(" ", "_") + "_10k_latest_llm_ready.txt"


def _flatten(result: dict) -> dict:
    """One wide row per company — risk lists joined with ' | '."""
    row = {
        "company_name": result["company_name"],
        "fiscal_year": result["fiscal_year"],
        "total_revenue": result["total_revenue"],
        "net_income": result["net_income"],
        "low_confidence_fields": " | ".join(result["low_confidence_fields"]),
    }
    for category, bullets in result["risk_factors"].items():
        row[category] = " | ".join(bullets)
    return row


def build_extraction_dataframe(companies: list[str]) -> pd.DataFrame:
    """
    Run extraction for every company, return a wide DataFrame (one row per company).

    Companies that fail (blob not found, JSON error, schema error) are skipped
    with a printed warning so one bad filing doesn't abort the whole batch.
    """

    rows = []
    for company in companies:
        blob_name = _company_to_blob_name(company)
        try:
            print(f"Extracting: {company}")
            result = extract_10k_from_blob(blob_name)
            rows.append(_flatten(result))
        except Exception as exc:
            print(f"  ⚠️  Skipped {company}: {exc}")

    return pd.DataFrame(rows)


if __name__ == "__main__":
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

    df = build_extraction_dataframe(companies)
    print(df.to_string())
    df.to_csv("10k_extractions.csv", index=False)
