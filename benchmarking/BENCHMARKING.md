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
| Diacritic variants | हूँ vs हूं (chandrabindu vs anusvara) | All models |
| Zero-width chars | ZWJ/ZWNJ inserted by some models | Various |

### Normalization pipeline (`normalize_indic.py`)

Applied to **both** hypothesis and reference before computing normalized metrics. Four stages, in order:

**1. Unicode / Indic normalization** (`normalize_unicode`)
- Unicode NFC canonical composition
- Strip zero-width characters (ZWJ U+200D, ZWNJ U+200C, ZWSP U+200B, BOM U+FEFF)
- `IndicNormalizerFactory("hi")` from `indic-nlp-library`: canonicalizes chandrabindu/anusvara, nukta, multi-part vowel signs

**2. Strip punctuation** (`strip_punctuation`)
- Removes: `, . ? ! ; : । | " ' " " ' ' ( ) [ ] { } < > … – — - / \ ~ @ # $ % ^ & * + = _`
- Both Latin and Devanagari punctuation

**3. Normalize numbers** (`normalize_numbers`)
- Regex matches digit sequences (with optional commas: `50,000`)
- Converts to Hindi words using the Indian number system: सौ (100), हजार (1,000), लाख (1,00,000), करोड़ (1,00,00,000)
- Custom lookup table covers all 100 unique Hindi words for integers 0–99
- Examples: `50000` → `पचास हजार`, `2024` → `दो हजार चौबीस`, `26` → `छब्बीस`
- Decimals left as-is; integers >99,99,99,999 left as-is

**4. Collapse whitespace** (`collapse_whitespace`)
- Multiple spaces → single space, strip leading/trailing

Each step is a standalone function so the error analysis can measure their individual impact.

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

Measures meaning similarity rather than surface form. Uses `paraphrase-multilingual-MiniLM-L12-v2` (a multilingual sentence-transformer that supports Hindi).

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
Raw WER  →  (−punct)  →  (−numbers)  →  (−diacritics)  →  nWER (genuine errors)
```

Each step subtracts one normalization layer. The deltas show:
- **Δpunct** — WER reduction from stripping punctuation alone
- **Δnumbers** — additional WER reduction from normalizing digits
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

---

## Results (helpdesk domain, 62 files)

From `comparison_helpdesk.csv`:

| Model | Files | Raw WER | Raw CER | nWER | nCER |
|---|---|---|---|---|---|
| saaras:v3 | 62 | 21.21% | 6.06% | **4.92%** | 2.74% |
| saarika:v2.5 | 60 | 20.40% | 5.75% | 12.15% | 3.86% |
| indic-conformer | 62 | 40.00% | 15.82% | 39.95% | 15.80% |
| vaani-whisper | 62 | 45.65% | 19.39% | 45.52% | 19.33% |
| mms-1b-all | 62 | 61.94% | 23.59% | 61.58% | 23.34% |
| indicwav2vec | 62 | 67.74% | 28.38% | 67.64% | 28.32% |
| whisper-large-v3 | 62 | 69.44% | 32.64% | 67.72% | 31.81% |

Key observations:
- **Saaras v3 drops from 21.21% raw WER to 4.92% nWER** — most of its "errors" were punctuation, not wrong words
- Saarika v2.5 also improves significantly (20.40% → 12.15%)
- GPU models barely change — their errors are genuine transcription mismatches, not formatting
- Saaras v3 is the clear winner after fair normalization

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
│   ├── load_ground_truth.py                 ← reads xlsx ground truth
│   └── extract_voice2voice_questions.py     ← extracts Q files from Voice2Voice.zip
└── results/
    └── comparison_helpdesk.csv              ← latest results
```

---

## Dependencies

Core benchmarking deps (in `pyproject.toml` under `[project.optional-dependencies] benchmarking`):

| Package | Purpose |
|---|---|
| `transformers`, `torch`, `torchaudio` | HuggingFace model inference |
| `indic-nlp-library` | Devanagari Unicode normalization |
| `sentence-transformers` | SemDist (semantic distance) via multilingual embeddings |
| `openpyxl` | Reading ground truth xlsx |
| `jiwer` | Reference WER library (available but we use our own Levenshtein) |

---

## References

- [Is Word Error Rate a good evaluation metric for Speech Recognition in Indic Languages?](https://arxiv.org/abs/2203.16601) — AWER/ACER for Hindi
- [What is lost in Normalization? Exploring Pitfalls in Multilingual ASR Model Evaluations](https://aclanthology.org/2024.emnlp-main.607.pdf) — EMNLP 2024, shows how Whisper's normalization destroys Indic diacritics
- [SeMaScore: a new evaluation metric for automatic speech recognition tasks](https://arxiv.org/abs/2401.07506) — semantic similarity for ASR
- [Indic NLP Library](https://github.com/anoopkunchukuttan/indic_nlp_library) — IndicNormalizer
- [Sarvam Saaras v3 docs](https://docs.sarvam.ai/api-reference-docs/getting-started/models/saaras)
