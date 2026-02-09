# Transcription Guidelines for bhAI Voice Bot

These guidelines ensure consistent, high-quality ground truth data for STT (Speech-to-Text) benchmarking. Following them enables fair model comparison and produces training data that improves future models.

---

## Core Principle

**Every spoken word must have exactly one Devanagari representation.**

---

## 1. Script: Devanagari Only

Write ALL words in Devanagari script, including English words.

| Do This | Not This |
|---------|----------|
| पीएफ | PF |
| ऑफिस | office |
| सैलरी | salary |
| डॉक्यूमेंट | document |

**Why?** Mixing scripts breaks WER (Word Error Rate) calculation. The STT model outputs Devanagari, so ground truth must match.

---

## 2. Punctuation: Skip It

- No periods `.`
- No commas `,`
- No question marks `?`
- No exclamation points `!`
- No quotation marks `"` `'`
- No parentheses `(` `)`

Just words separated by single spaces.

| Do This | Not This |
|---------|----------|
| मेरा पीएफ कितना है | मेरा पीएफ कितना है? |
| हाँ मुझे चाहिए | हाँ, मुझे चाहिए। |

**Why?** Punctuation is removed during WER normalization anyway. Adding it just creates extra work and potential inconsistencies.

---

## 3. English Words in Devanagari

Transliterate phonetically based on how the word was **actually spoken**, not formal spelling.

### Quick Reference Table

| English Spoken | Write in Devanagari |
|----------------|---------------------|
| PF | पीएफ |
| ESI | ईएसआई |
| salary | सैलरी |
| office | ऑफिस |
| document | डॉक्यूमेंट |
| Aadhaar | आधार |
| card | कार्ड |
| update | अपडेट |
| loan | लोन |
| leave | लीव |
| form | फॉर्म |
| account | अकाउंट |
| amount | अमाउंट |
| mobile | मोबाइल |
| number | नंबर |
| problem | प्रॉब्लम |
| okay / OK | ओके |
| sorry | सॉरी |
| please | प्लीज |
| sir | सर |
| madam | मैडम |
| hello | हेलो / हॅलो |
| thank you | थैंक यू |
| certificate | सर्टिफिकेट |
| Ayushman | आयुष्मान |
| ration | राशन |
| scholarship | स्कॉलरशिप |
| post office | पोस्ट ऑफिस |
| bank | बैंक |
| insurance | इंश्योरेंस |

**Key principle:** Don't overthink spelling. Write what you hear. If someone says "डॉक्यूमेंट्स" with a trailing "स", write it that way.

---

## 4. Numbers

Write numbers exactly as spoken, in Devanagari words.

| Spoken | Write |
|--------|-------|
| "fifty thousand" | पचास हजार |
| "two-three months" | दो तीन महीने |
| "26th January" | छब्बीस जनवरी |
| "2024" (said as year) | दो हजार चौबीस |
| "RS 500" | पाँच सौ रुपये |

**Do NOT use:**
- Numerals: 50000, 2-3, 26
- Mixed: पचास 1000

---

## 5. Filler Words and Hesitations

**Include them.** These are part of natural speech.

| Include These |
|---------------|
| हाँ |
| हम्म |
| अरे |
| ओके |
| तो |
| ना |
| है ना |
| मतलब |

### Include Repetitions and False Starts

If someone says: "मुझे मेरा... मेरा पीएफ चाहिए"

Write exactly: `मुझे मेरा मेरा पीएफ चाहिए`

**Why?** STT models transcribe what's spoken. Ground truth should match actual speech, not cleaned-up versions.

---

## 6. Unclear Audio

For completely unintelligible segments, use the marker: `[unclear]`

| Situation | Write |
|-----------|-------|
| Can't hear at all | मुझे [unclear] चाहिए |
| Background noise | [unclear] पीएफ की जानकारी |
| Multiple unclear words | [unclear] |

**Rules:**
- Don't guess. If you're not sure, mark it `[unclear]`
- If you can partially hear, write what you can: "मुझे [unclear] कार्ड चाहिए"
- One `[unclear]` per unintelligible segment (not per word)

---

## 7. Multiple Speakers

- Transcribe **only the primary speaker** (the worker asking the question)
- Ignore background voices, unless they're clearly part of the intended message
- If someone else speaks briefly and it's relevant, include it

---

## 8. Language Variations

Our audio contains Hindi, Marathi, and occasionally other languages.

**Transcribe in the script of the language spoken:**
- Hindi → Devanagari
- Marathi → Devanagari
- Punjabi (Gurmukhi) → If Sarvam outputs Gurmukhi, keep it as-is for now

**Code-switching within a sentence:**
If someone switches between Hindi and Marathi mid-sentence, transcribe exactly as spoken. Both use Devanagari, so this works naturally.

---

## 9. Common Mistakes to Avoid

### Mistake 1: Adding Punctuation
```
❌ मेरा पीएफ कितना है?
✅ मेरा पीएफ कितना है
```

### Mistake 2: Mixing Scripts
```
❌ मेरा PF amount जानना है
✅ मेरा पीएफ अमाउंट जानना है
```

### Mistake 3: Correcting Grammar
```
❌ मुझे पीएफ निकालना है (grammatically correct)
✅ मुझे पीएफ निकालने का है (as actually spoken)
```

### Mistake 4: Removing Filler Words
```
❌ मुझे पीएफ चाहिए
✅ हाँ मुझे पीएफ चाहिए (if "हाँ" was spoken)
```

### Mistake 5: Using Numerals
```
❌ मुझे 50000 रुपये चाहिए
✅ मुझे पचास हजार रुपये चाहिए
```

### Mistake 6: Over-correcting English Spellings
```
❌ डॉक्युमेंट (trying to be "correct")
✅ डॉक्यूमेंट (as commonly pronounced)
```

Both are acceptable - just be consistent with how it sounds.

---

## 10. Quality Checklist

Before saving a transcription, verify:

- [ ] All words are in Devanagari (no English letters)
- [ ] No punctuation marks
- [ ] Numbers written as words
- [ ] Filler words included
- [ ] Unclear parts marked with `[unclear]`
- [ ] Matches what was actually spoken (not corrected grammar)

---

## Why These Rules Matter

### For WER Calculation
Word Error Rate compares your transcription to the model's output word-by-word. Inconsistent formatting (punctuation, mixed scripts, numerals) artificially inflates error rates.

### For Model Comparison
When benchmarking multiple STT models, consistent ground truth ensures fair comparison. One model shouldn't score worse just because the reference uses different conventions.

### For Training Data
If we fine-tune models later, clean and consistent transcriptions produce better training data.

### For Reproducibility
Anyone should be able to verify our benchmarks. Clear guidelines make results reproducible.

---

## References

These guidelines are informed by:
- [Hugging Face ASR Evaluation Guide](https://huggingface.co/learn/audio-course/en/chapter5/evaluation)
- [AI4Bharat Vistaar Benchmark](https://github.com/AI4Bharat/vistaar)
- [IndicVoices Dataset](https://arxiv.org/html/2403.01926v1)
- [WER for Indic Languages Research](https://www.academia.edu/87354590/Is_Word_Error_Rate_a_good_evaluation_metric_for_Speech_Recognition_in_Indic_Languages)

---

## Questions?

If you encounter a situation not covered here, ask before guessing. Consistency is more important than any single transcription.
