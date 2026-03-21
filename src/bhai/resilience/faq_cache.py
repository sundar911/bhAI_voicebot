"""
FAQ cache parsed from knowledge base markdown files.

Provides fast keyword-based matching for common artisan questions,
allowing the pipeline to skip the LLM call when a high-confidence
FAQ match is found.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("bhai.resilience.faq_cache")


@dataclass
class FAQEntry:
    """A single FAQ question-answer pair from the knowledge base."""

    question: str
    answer: str
    domain: str
    source_file: str
    keywords: set


def _tokenize(text: str) -> set:
    """
    Simple tokenizer for Hindi/Hinglish text.

    Strips punctuation, lowercases, and splits on whitespace.
    Removes very short tokens (1 char) that are usually particles.
    """
    # Remove punctuation except Hindi characters
    cleaned = re.sub(r'["""\'?!.,;:→\-—()[\]{}]', " ", text)
    tokens = cleaned.lower().split()
    # Filter out single-char tokens (common particles like "ka", "ki" are 2 chars)
    return {t for t in tokens if len(t) > 1}


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


class FAQCache:
    """
    In-memory FAQ cache built from knowledge base markdown files.

    Parses ``## Common Questions`` sections from .md files and provides
    simple keyword-based matching. Conservative threshold ensures we
    only return high-confidence matches.
    """

    def __init__(self, knowledge_base_dir: Path, threshold: float = 0.6):
        """
        Initialize FAQ cache by parsing all domain knowledge base files.

        Args:
            knowledge_base_dir: Root of the knowledge base directory
            threshold: Minimum Jaccard similarity for a match (0.0-1.0)
        """
        self.threshold = threshold
        self.entries: List[FAQEntry] = []
        self._load_all(knowledge_base_dir)
        logger.info("FAQ cache loaded: %d entries", len(self.entries))

    def _load_all(self, kb_dir: Path):
        """Parse FAQ entries from all domain directories."""
        if not kb_dir.exists():
            return

        for domain_dir in kb_dir.iterdir():
            if not domain_dir.is_dir() or domain_dir.name in ("shared", "users"):
                continue

            domain = domain_dir.name
            for md_file in domain_dir.glob("*.md"):
                self._parse_file(md_file, domain)

    def _parse_file(self, md_path: Path, domain: str):
        """
        Extract FAQ pairs from a markdown file.

        Expected format:
            ## Common Questions

            ### "Salary kyun kata?"
            → Answer text here.

            ### "Overtime milega?"
            → Another answer.
        """
        try:
            content = md_path.read_text(encoding="utf-8")
        except Exception:
            return

        # Find the "Common Questions" section
        sections = re.split(r"^## ", content, flags=re.MULTILINE)
        faq_section = None
        for section in sections:
            if section.strip().startswith("Common Questions"):
                faq_section = section
                break

        if not faq_section:
            return

        # Parse ### "question" followed by → answer
        entries = re.split(r"^### ", faq_section, flags=re.MULTILINE)
        for entry in entries[1:]:  # skip the header
            lines = entry.strip().splitlines()
            if not lines:
                continue

            # Extract question (may be in quotes)
            question_line = lines[0].strip().strip('"').strip("'").strip()
            if not question_line:
                continue

            # Collect answer lines (start with → or are plain text after question)
            answer_parts = []
            for line in lines[1:]:
                stripped = line.strip()
                if stripped.startswith("→"):
                    answer_parts.append(stripped[1:].strip())
                elif stripped:
                    answer_parts.append(stripped)

            if not answer_parts:
                continue

            answer = " ".join(answer_parts)
            keywords = _tokenize(question_line)

            self.entries.append(
                FAQEntry(
                    question=question_line,
                    answer=answer,
                    domain=domain,
                    source_file=md_path.name,
                    keywords=keywords,
                )
            )

    def match(self, transcript: str) -> Optional[FAQEntry]:
        """
        Find the best FAQ match for a user transcript.

        Args:
            transcript: User's transcribed speech

        Returns:
            Best matching FAQEntry if similarity >= threshold, else None.
        """
        if not self.entries:
            return None

        query_tokens = _tokenize(transcript)
        if not query_tokens:
            return None

        best_entry = None
        best_score = 0.0

        for entry in self.entries:
            score = _jaccard_similarity(query_tokens, entry.keywords)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_score >= self.threshold and best_entry is not None:
            logger.info(
                "FAQ match: score=%.2f question='%s' file=%s",
                best_score,
                best_entry.question,
                best_entry.source_file,
            )
            return best_entry

        return None

    def format_response(self, entry: FAQEntry) -> str:
        """
        Wrap a FAQ answer in bhAI's warm style.

        Adds a natural opener and follow-up prompt.
        """
        return f"{entry.answer}\n\nAur kuch poochna hai?"
