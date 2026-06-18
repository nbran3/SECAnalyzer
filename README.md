SEC Filing Intelligence Pipeline


Status: Work in progress. This README is a temporary working doc, not a final polished version.



What this is

An end-to-end pipeline that ingests SEC 10-K filings, uses an LLM (Claude)
to extract structured financial and risk data from the raw filing text,
and stores the results in a queryable medallion architecture.

The core problem this solves: 10-K filings are long, unstructured, legal-style
documents. This pipeline turns them into structured, typed records that can be
queried, compared across companies, and analyzed at scale — without a human
reading every filing by hand.

Architecture

EDGAR (raw HTML filings)
        |
        v
   Bronze Layer        -- raw filing HTML/text, stored as-is
        |
        v
   LLM Extraction       -- Claude (Haiku) extracts structured fields
        |               -- Pydantic schema validation (dead-letter on failure)
        v
   Silver Layer         -- validated structured JSON records
        |
        v
   Gold Layer           -- analytical views / dbt models (planned)
        |
        v
   Query Layer          -- RAG / agentic NL querying (planned)