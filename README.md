# 🧠 Metadata Intelligence Platform

> An AI-powered metadata enrichment and validation system for enterprise data warehouses.

## 📌 Project Overview

This project simulates a real-world enterprise data environment with incomplete, incorrect, and multilingual metadata — and builds an agent-based AI pipeline to automatically **enrich**, **validate**, and **score** table/column descriptions using LLMs.

### Key Capabilities

- 🔍 **Metadata Quality Scoring** — Evaluates column descriptions using a Clarity Score engine
- 🤖 **Generator & Critic Agent Pipeline** — Auto-generates and critiques column/table descriptions
- 🔗 **ETL Lineage Graph Traversal** — Loops through source-target lineage (XML/JSON) for full data tracing
- ⚠️ **Risk Classification** — Tags fields as `LOW_RISK` / `HIGH_RISK` with popup-style alerts
- 📋 **Lookup Gap Detection** — Identifies low-cardinality columns missing LKP table mappings
- ✅ **Validation Engine** — Detects mismatches between documented and actual column values
- 📊 **Daily Reporting Dashboard** — Slide-ready daily action report with UI verification

---

## 🏗️ Architecture

```
metadata-intelligence-platform/
│
├── data/
│   ├── tables/           # Synthetic table metadata (JSON) — some incomplete, wrong, English
│   ├── etl/              # ETL lineage source-target definitions (XML + JSON)
│   ├── lineage/          # Graph-traversal lineage maps (loop detection)
│   └── schemas/          # Schema list + conceptual model context
│
├── docs/
│   ├── functional_requirements/   # Functional requirement docs (some missing)
│   ├── toa/                       # TOA documents + analysis queries (some missing)
│   └── ddl/                       # CREATE scripts (DDL) for tables
│
├── agents/
│   ├── generator_agent.py         # LLM-based metadata description generator
│   ├── critic_agent.py            # Validates and scores generated descriptions
│   └── orchestrator.py            # Runs the full pipeline
│
├── scripts/
│   ├── clarity_scorer.py          # Clarity Score calculation engine
│   ├── cardinality_checker.py     # Low-cardinality / lookup gap detector
│   ├── lineage_crawler.py         # ETL lineage loop traversal
│   └── risk_classifier.py         # LOW/HIGH risk field tagger
│
├── ui/
│   └── dashboard.html             # Daily report dashboard (UI verification)
│
├── tests/
│   └── test_validators.py         # Validation test suite
│
├── requirements.txt
└── README.md
```

---

## 🚀 Quick Start

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/metadata-intelligence-platform.git
cd metadata-intelligence-platform

# Install dependencies
pip install -r requirements.txt

# Set your Anthropic API key
export ANTHROPIC_API_KEY=your_key_here

# Run the full pipeline
python agents/orchestrator.py

# Open the dashboard
open ui/dashboard.html
```

---

## 🤖 Agent Pipeline

### Generator Agent
- Reads raw table/column metadata
- Calls Claude API to generate enriched descriptions
- Context-aware: uses schema, conceptual model, DDL, and TOA docs if available
- Handles missing/partial documentation gracefully

### Critic Agent
- Evaluates generated descriptions for:
  - **Completeness** — Does it explain the column in full context?
  - **Accuracy** — Does it match DDL, lookup values, and functional docs?
  - **Clarity Score** — Hierarchical, unambiguous, no divergent interpretations
- Outputs a score (0–100) and improvement feedback

### Orchestrator
- Loops through all tables → columns
- Triggers Generator → Critic → Re-generate if score < threshold
- Writes enriched metadata back to `data/tables/`

---

## ⚠️ Risk Classification

Columns are tagged as:

| Risk Level | Criteria |
|---|---|
| `HIGH_RISK` | Vague description, missing lookup, undocumented value range, no functional doc |
| `LOW_RISK` | Clear description, lookup present, value range validated, documented |

The dashboard displays these as colored popup-style badges for stakeholder review.

---

## 🔗 ETL Lineage

Lineage data is stored in `data/etl/` as XML and JSON. The `lineage_crawler.py` script:

- Parses source → target mappings
- Builds a directed graph
- Detects loops (circular dependencies)
- Identifies orphaned tables (no upstream/downstream)

---

## 📊 Problematic Scenarios Covered

| Scenario | Example |
|---|---|
| Vague description | `ACILIS_TARIHI: Açılış tarihidir.` → enriched with schema context |
| Wrong domain in description | `INT_SHK_A_30GCK_ADT_LM` labeled as 60-day but actually 30-day |
| Value mismatch | Column documented as `1,2,3` but actual data contains `4` |
| Missing LKP table | Column with values `0,1,2` has no lookup reference in data model |
| English description in Turkish schema | Auto-translated and contextualized |
| No functional requirement doc | Flagged; description generated from DDL + schema only |
| Partitioned table cardinality | Consolidated across partitions before cardinality check |

---

## 📋 Daily Report Format

Each team member submits a daily slide update (see `ui/dashboard.html`) with:
- ✅ What I did today
- ❌ What I couldn't complete
- 🔜 Next steps
- 📸 UI verification screenshot

---

## 📚 References

- Conceptual model: `data/schemas/conceptual_model.json`
- Schema list: `data/schemas/schema_list.json`
- Clarity scoring methodology: `docs/toa/clarity_score_methodology.md`
