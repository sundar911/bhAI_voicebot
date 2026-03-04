# bhAI STT Benchmarking

Evaluating speech-to-text models for Hindi/Marathi voice notes from Tiny Miracles artisans.

## Models

We benchmark 7 STT models — 2 API-based (Sarvam) and 5 open-source (GPU):

| Registry name | Model ID | Type | Notes |
|---|---|---|---|
| `sarvam_saaras` | saaras:v3 | API (Sarvam) | Latest. Silence-aware chunking for audio >30s. Outputs punctuation + sometimes digits. |
| `sarvam_saarika` | saarika:v2.5 | API (Sarvam) | Older baseline. Also outputs some punctuation in Marathi. |
| `indic_conformer` | ai4bharat/indic-conformer-600m-multilingual | HuggingFace | 600M params. All 22 official Indian languages. Clean Devanagari output. |
| `vaani_whisper` | ARTPARK-IISc/whisper-large-v3-vaani-hindi | HuggingFace | Fine-tuned on Vaani + IndicVoices + FLEURS. Hindi-specialized. |
| `whisper_large_v3` | openai/whisper-large-v3 | HuggingFace | General multilingual baseline. Outputs question marks. |
| `meta_mms` | facebook/mms-1b-all | HuggingFace | Lightweight (~2GB VRAM). Wav2Vec2 with language adapters. |
| `indic_wav2vec` | ai4bharat/indicwav2vec-hindi | HuggingFace | Wav2Vec2-based CTC. 317M params. Hindi only. |

Model implementations live in `src/bhai/stt/` with a registry in `src/bhai/stt/registry.py`.

## Audio dataset

Source: Tiny Miracles' Voice2Voice SharePoint folder. Audio files follow the pattern `{DEPT_PREFIX}_{Q|Ans}_{NUMBER}.ogg` (see CLAUDE.md for full naming convention).

We only benchmark **question** files (`_Q_` pattern), not answer files.

| Domain | Folder | Prefix | Q files |
|---|---|---|---|
| Helpdesk | `helpdesk/` | Hd / HD | 114 |
| HR-Admin | `hr_admin/` | HR_Ad | 30 |
| Production | `production/` | P | 28 |
| Grievance | `grievance/` | GV | 2 |
| NextGen | `nextgen/` | NG | 2 |
| **Total** | | | **176** |

Audio is packaged in `sharepoint_audio.zip` (question files only). On the EC2 benchmarking VM, unzip to `data/sharepoint_sync/`.

## Ground truth

Human-reviewed transcriptions live in `source_of_truth_transcriptions.xlsx` with columns: Department, File Name, Human Reviewed.

Transcription guidelines are documented in `data/transcription_dataset/TRANSCRIPTION_GUIDELINES.md`. Key rules:
- **Devanagari only** — no Latin script (PF → पीएफ)
- **No punctuation** — no commas, periods, question marks
- **Numbers as words** — 50000 → पचास हजार
- **Include fillers** — हाँ, हम्म, अरे, etc.
- **Transcribe as spoken** — don't correct grammar

---

## Text normalization

Different models produce different surface formatting for the same audio. Without normalization, metrics penalize formatting choices rather than transcription quality:

| Issue | Example | Affected models |
|---|---|---|
| Punctuation | `मैडम, मैं चंदा देवी` vs `मैडम मैं चंदा देवी` | Saaras v3, Saarika v2.5, Whisper |
| Numbers as digits | `50000 रुपये` vs `पचास हजार रुपये` | Saaras v3 |
| Time as digits | `6.30 बजे` vs `साढ़े छह बजे` | Saaras v3 |
| Currency symbols | `₹1000` vs `एक हजार रुपये` | Saaras v3 |
| Diacritic variants | हूँ vs हूं (chandrabindu vs anusvara) | All models |
| Zero-width chars | ZWJ/ZWNJ inserted by some models | Various |

### Normalization pipeline (`normalize_indic.py`)

Applied to **both** hypothesis and reference before computing normalized metrics. Six stages, in order:

**1. Unicode / Indic normalization** (`normalize_unicode`)
- Unicode NFC canonical composition
- Strip zero-width characters (ZWJ U+200D, ZWNJ U+200C, ZWSP U+200B, BOM U+FEFF)
- `IndicNormalizerFactory("hi")` from `indic-nlp-library`: canonicalizes chandrabindu/anusvara, nukta, multi-part vowel signs

**2. Normalize time expressions** (`normalize_time`)
- Pattern: `(\d+)\.(\d+)\s*बजे` → Hindi time + बजे
- Context-aware: `6.30 बजे` → `साढ़े छह बजे`, `1.30 बजे` → `डेढ़ बजे`, `3.15 बजे` → `सवा तीन बजे`, `1.45 बजे` → `पौने दो बजे`
- Must run BEFORE general number normalization so "6.30" isn't split into digits

**3. Normalize currency** (`normalize_currency`)
- Pattern: `₹\s*(\d[\d,]*)` → Hindi number + रुपये
- Examples: `₹1000` → `एक हजार रुपये`, `₹50,000` → `पचास हजार रुपये`

**4. Normalize numbers** (`normalize_numbers`)
- Regex matches remaining digit sequences (with optional commas: `50,000`)
- Converts to Hindi words using the Indian number system: सौ (100), हजार (1,000), लाख (1,00,000), करोड़ (1,00,00,000)
- Custom lookup table covers all 100 unique Hindi words for integers 0–99
- Examples: `50000` → `पचास हजार`, `2024` → `दो हजार चौबीस`, `26` → `छब्बीस`
- Decimals: integer part + "दशमलव" + fractional digits; integers >99,99,99,999 left as-is

**5. Strip punctuation** (`strip_punctuation`)
- Removes: `, . ? ! ; : । | " ' " " ' ' ( ) [ ] { } < > … – — - / \ ~ @ # $ % ^ & * + = _ ₹ ₨ $ € £ ¥`
- Both Latin and Devanagari punctuation, plus currency symbols not caught by step 3

**6. Collapse whitespace** (`collapse_whitespace`)
- Multiple spaces → single space, strip leading/trailing

Each step is a standalone function so the error analysis can measure their individual impact.

**Pipeline order matters**: Time and currency must be normalized before punctuation stripping, otherwise "6.30" loses its dot and becomes "630" → wrong Hindi conversion.

### What normalization does NOT do

- **Script transliteration** — English words like "PF" are left as-is. The ground truth guidelines require all Devanagari, so this is an actual transcription difference, not formatting noise.
- **Spelling correction** — `डॉक्यूमेंट` vs `डॉक्युमेंट` are treated as different (both are valid spellings of "document" in Devanagari, and this is a genuine model difference).

---

## Metrics

We report 6 metrics per model. The table is sorted by nWER (the primary fair-comparison metric).

### Raw WER (Word Error Rate)

Standard Levenshtein-based WER on the raw model output vs raw ground truth. No normalization applied.

```
WER = edit_distance(hypothesis_words, reference_words) / len(reference_words)
```

Kept for backward compatibility and to show "as-is" model behavior.

### Raw CER (Character Error Rate)

Same as WER but at the character level. More granular for Devanagari, where a single character substitution (e.g., wrong matra) inflates WER for the whole word.

```
CER = edit_distance(hypothesis_chars, reference_chars) / len(reference_chars)
```

### nWER (Normalized Word Error Rate)

WER computed after applying the full normalization pipeline to both hypothesis and reference. This is the **primary ranking metric** — it strips formatting noise and measures actual transcription quality.

### nCER (Normalized Character Error Rate)

CER after full normalization.

### SemDist (Semantic Distance)

Measures meaning similarity rather than surface form. Uses `krutrim-ai-labs/Vyakyarth` (Vyakyarth-1 Indic Embedding model, 768-dim, supports Hindi + Marathi + 8 other Indian languages).

```
SemDist = 1 - cosine_similarity(embed(hypothesis), embed(reference))
```

Range: 0 (identical meaning) to 2 (opposite meaning). Computed on normalized text.

Useful when WER is high but the transcription is semantically correct (e.g., paraphrasing, synonym choice, different word order).

### Why not AWER/ACER?

AWER/ACER (Adjusted WER/CER) from the 2022 paper "Is Word Error Rate a good evaluation metric for Speech Recognition in Indic Languages?" (arXiv 2203.16601) account for legitimate Hindi spelling variants. Our IndicNormalizer already canonicalizes the same variant classes (chandrabindu/anusvara, nukta). AWER/ACER would add marginal improvement (~3% WER, ~7% CER) on top of our normalization. Can revisit if needed.

---

## Error analysis waterfall

`error_analysis.py` breaks down each model's WER into layers, showing how much is due to formatting vs genuine transcription errors:

```
Raw WER  →  (−numbers/time/currency)  →  (−punct)  →  (−diacritics)  →  nWER (genuine errors)
```

Each step subtracts one normalization layer. The deltas show:
- **Δnumbers** — WER reduction from normalizing time, currency, and digit expressions
- **Δpunct** — additional WER reduction from stripping punctuation
- **Δdiacritics** — additional reduction from Indic Unicode normalization
- **genuine** — remaining nWER = actual transcription errors

This reveals each model's "error fingerprint". For example, Saaras v3 shows a large Δpunct (it outputs punctuation that the ground truth doesn't have) but very low genuine errors. Models that hallucinate show high genuine errors regardless of normalization.

---

## Running the benchmarks

### Prerequisites

```bash
# On EC2 — install benchmarking dependencies
pip install -e ".[benchmarking]"

# Unzip audio files
unzip sharepoint_audio.zip -d data/sharepoint_sync/

# Ensure ground truth xlsx is at project root
ls source_of_truth_transcriptions.xlsx
```

### Generate transcriptions

```bash
# Full suite (all models, all domains)
bash benchmarking/run_benchmark.sh

# Specific models/domains
bash benchmarking/run_benchmark.sh --models "sarvam_saaras indic_conformer" --domains "helpdesk"

# Sarvam models (API-based, no GPU needed)
bash benchmarking/run_benchmark.sh --models "sarvam_saaras" --device cpu
```

Transcriptions are saved as JSONL files in `data/transcription_dataset/{domain}/transcriptions_{model}.jsonl`.

### Compare models

```bash
# All domains combined (default)
python3 benchmarking/scripts/compare_models.py

# Single domain
python3 benchmarking/scripts/compare_models.py --domain helpdesk

# Save to CSV
python3 benchmarking/scripts/compare_models.py --output benchmarking/results/comparison.csv
```

### Error analysis

```bash
python3 benchmarking/scripts/error_analysis.py --domain helpdesk
python3 benchmarking/scripts/error_analysis.py --domain helpdesk --output benchmarking/results/error_analysis_helpdesk.csv
```

### Statistical significance

```bash
# Full report (binomial CI, bootstrap, Wilcoxon, domain consistency, power analysis)
python3 benchmarking/scripts/statistical_significance.py

# Save structured results to JSON
python3 benchmarking/scripts/statistical_significance.py --output benchmarking/results/significance.json
```

---

## Results (all domains, 175 files)

From `comparison_all.csv`:

| Model | Files | Raw WER | Raw CER | nWER | nCER | SemDist |
|---|---|---|---|---|---|---|
| saaras:v3 | 175 | 19.88% | 7.28% | **6.76%** | 3.83% | 0.0371 |
| saarika:v2.5 | 175 | 18.86% | 7.44% | 12.83% | 5.51% | 0.0614 |
| indic-conformer | 175 | 25.89% | 11.04% | 25.80% | 10.99% | 0.1345 |
| vaani-whisper | 175 | 39.77% | 25.99% | 39.52% | 25.89% | 0.1792 |
| mms-1b-all | 175 | 51.70% | 22.31% | 51.60% | 22.07% | 0.3565 |
| indicwav2vec | 175 | 55.28% | 23.77% | 55.22% | 23.68% | 0.3517 |
| whisper-large-v3 | 175 | 58.82% | 37.72% | 57.47% | 37.20% | 0.3156 |

Key observations:
- **Saaras v3 drops from 19.88% raw WER to 6.76% nWER** — most of its "errors" were punctuation and digit formatting, not wrong words
- Saarika v2.5 also improves significantly (18.86% → 12.83%)
- GPU models barely change — their errors are genuine transcription mismatches, not formatting
- Saaras v3 is the clear winner after fair normalization, confirmed by statistical significance testing

### Statistical significance

`statistical_significance.py` validates the findings with 5 tests:

1. **Binomial CIs**: saaras 95% CI [6.09%, 7.44%] vs saarika [11.94%, 13.73%] — non-overlapping
2. **Paired bootstrap** (10,000 iterations): p < 0.0001 for saaras vs all competitors
3. **Wilcoxon signed-rank**: p < 0.0001, saaras wins on 120/175 individual recordings
4. **Per-domain consistency**: saaras ranks #1 in all 3 domains with sufficient data
5. **Power analysis**: 99.9% power at N=175 — sample size is more than adequate

See `benchmarking/results/significance.json` for full structured output.

---

## File structure

```
benchmarking/
├── BENCHMARKING.md               ← this file
├── run_benchmark.sh              ← orchestrates full pipeline on EC2
├── configs/
│   └── models.yaml               ← model registry + dataset config
├── scripts/
│   ├── generate_initial_transcriptions.py   ← run STT models on audio
│   ├── transcribe_questions.py              ← Sarvam-specific batch transcription
│   ├── compare_models.py                    ← main comparison (6 metrics)
│   ├── compute_wer.py                       ← WER/CER/SemDist computation
│   ├── normalize_indic.py                   ← text normalization pipeline
│   ├── error_analysis.py                    ← waterfall error breakdown
│   ├── statistical_significance.py          ← statistical validation (5 tests)
│   ├── load_ground_truth.py                 ← reads xlsx ground truth
│   ├── download_audio_from_sharepoint.py    ← SharePoint audio sync
│   └── extract_voice2voice_questions.py     ← extracts Q files from Voice2Voice.zip
└── results/
    ├── comparison_all.csv                   ← all-domains results
    ├── comparison_{domain}.csv              ← per-domain results
    └── significance.json                    ← statistical significance output
```

---

## Dependencies

Core benchmarking deps (in `pyproject.toml` under `[project.optional-dependencies] benchmarking`):

| Package | Purpose |
|---|---|
| `transformers`, `torch`, `torchaudio` | HuggingFace model inference |
| `indic-nlp-library` | Devanagari Unicode normalization |
| `sentence-transformers` | SemDist via Vyakyarth-1 Indic embeddings |
| `scipy` | Statistical significance testing |
| `openpyxl` | Reading ground truth xlsx |
| `jiwer` | Reference WER library (available but we use our own Levenshtein) |

---

## References

- [Is Word Error Rate a good evaluation metric for Speech Recognition in Indic Languages?](https://arxiv.org/abs/2203.16601) — AWER/ACER for Hindi
- [What is lost in Normalization? Exploring Pitfalls in Multilingual ASR Model Evaluations](https://aclanthology.org/2024.emnlp-main.607.pdf) — EMNLP 2024, shows how Whisper's normalization destroys Indic diacritics
- [SeMaScore: a new evaluation metric for automatic speech recognition tasks](https://arxiv.org/abs/2401.07506) — semantic similarity for ASR
- [Indic NLP Library](https://github.com/anoopkunchukuttan/indic_nlp_library) — IndicNormalizer
- [Sarvam Saaras v3 docs](https://docs.sarvam.ai/api-reference-docs/getting-started/models/saaras)
