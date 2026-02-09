"""
Custom Streamlit components for bhAI transcription review.
"""

import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
import html as html_lib

# Get the path to the component's HTML file
_COMPONENT_DIR = Path(__file__).parent


def devanagari_editor(initial_value: str = "", height: int = 400, key: str = None) -> str:
    """
    Custom editor with cursor-aware Devanagari keyboard.

    Uses inline HTML component. The edited text is stored in a session state
    variable that gets updated via a hidden input trick.

    Args:
        initial_value: Initial text to display in the editor
        height: Height of the component in pixels
        key: Unique key for the component

    Returns:
        The current text content of the editor
    """
    # Escape the initial value for safe HTML embedding
    escaped_value = html_lib.escape(initial_value) if initial_value else ""

    # Session state key for this editor
    state_key = f"devanagari_editor_{key}" if key else "devanagari_editor_default"

    # Initialize session state
    if state_key not in st.session_state:
        st.session_state[state_key] = initial_value

    html_content = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            * {{
                box-sizing: border-box;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }}
            body {{
                margin: 0;
                padding: 10px;
                background: transparent;
            }}
            #editor {{
                width: 100%;
                min-height: 80px;
                padding: 12px;
                border: 1px solid #ddd;
                border-radius: 6px;
                font-size: 16px;
                line-height: 1.8;
                outline: none;
                background: white;
                white-space: pre-wrap;
            }}
            #editor:focus {{
                border-color: #ff4b4b;
                box-shadow: 0 0 0 2px rgba(255, 75, 75, 0.1);
            }}
            .keyboard {{
                margin-top: 12px;
            }}
            .keyboard-section {{
                margin-bottom: 8px;
            }}
            .keyboard-label {{
                font-size: 11px;
                color: #666;
                margin-bottom: 4px;
                font-weight: 500;
            }}
            .keyboard-row {{
                display: flex;
                flex-wrap: wrap;
                gap: 4px;
            }}
            .char-btn {{
                min-width: 32px;
                height: 32px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: white;
                cursor: pointer;
                font-size: 16px;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.1s;
            }}
            .char-btn:hover {{
                background: #f0f0f0;
                border-color: #ccc;
            }}
            .char-btn:active {{
                background: #e0e0e0;
            }}
            .marker-btn {{
                padding: 4px 8px;
                font-size: 12px;
                background: #fff3cd;
                border-color: #ffc107;
            }}
            .marker-btn:hover {{
                background: #ffe69c;
            }}
            .section-toggle {{
                font-size: 12px;
                color: #666;
                cursor: pointer;
                user-select: none;
                margin-bottom: 4px;
                padding: 4px;
                background: #f5f5f5;
                border-radius: 4px;
            }}
            .section-toggle:hover {{
                background: #eee;
            }}
            .collapsible {{
                overflow: hidden;
                max-height: 0;
                transition: max-height 0.3s;
            }}
            .collapsible.open {{
                max-height: 300px;
            }}
            .copy-section {{
                margin-top: 12px;
                padding: 8px;
                background: #e8f4ea;
                border-radius: 6px;
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .copy-btn {{
                padding: 8px 16px;
                background: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-weight: 500;
            }}
            .copy-btn:hover {{
                background: #218838;
            }}
            .copy-status {{
                font-size: 13px;
                color: #155724;
            }}
        </style>
    </head>
    <body>
        <div id="editor" contenteditable="true">{escaped_value}</div>

        <div class="copy-section">
            <button class="copy-btn" onclick="copyText()">Copy Text</button>
            <span class="copy-status" id="copyStatus">Copy the text, then paste it in the text box below before saving</span>
        </div>

        <div class="keyboard">
            <div class="keyboard-section">
                <div class="keyboard-label">Quick Markers</div>
                <div class="keyboard-row">
                    <button class="char-btn marker-btn" onclick="insertText(' [unclear] ')">unclear</button>
                    <button class="char-btn marker-btn" onclick="insertText(' [noise] ')">noise</button>
                    <button class="char-btn marker-btn" onclick="insertText(' [overlap] ')">overlap</button>
                    <button class="char-btn" onclick="insertText(' ')" title="Space">_</button>
                </div>
            </div>

            <div class="keyboard-section">
                <div class="keyboard-label">Vowels (Swar)</div>
                <div class="keyboard-row" id="vowels"></div>
            </div>

            <div class="keyboard-section">
                <div class="keyboard-label">Matras</div>
                <div class="keyboard-row" id="matras"></div>
            </div>

            <div class="keyboard-section">
                <div class="section-toggle" onclick="toggleSection('consonants')">
                    Consonants (Vyanjan) <span id="consonants-toggle">+</span>
                </div>
                <div class="collapsible" id="consonants">
                    <div class="keyboard-row" id="consonants-row"></div>
                </div>
            </div>

            <div class="keyboard-section">
                <div class="section-toggle" onclick="toggleSection('extras')">
                    Conjuncts & Extras <span id="extras-toggle">+</span>
                </div>
                <div class="collapsible" id="extras">
                    <div class="keyboard-row" id="extras-row"></div>
                </div>
            </div>

            <div class="keyboard-section">
                <div class="section-toggle" onclick="toggleSection('numbers')">
                    Numbers <span id="numbers-toggle">+</span>
                </div>
                <div class="collapsible" id="numbers">
                    <div class="keyboard-row" id="numbers-row"></div>
                </div>
            </div>
        </div>

        <script>
            const VOWELS = 'अ आ इ ई उ ऊ ऋ ए ऐ ओ औ अं अः'.split(' ');
            const MATRAS = 'ा ि ी ु ू ृ े ै ो ौ ं ः ँ ्'.split(' ');
            const CONSONANTS = [
                'क', 'ख', 'ग', 'घ', 'ङ',
                'च', 'छ', 'ज', 'झ', 'ञ',
                'ट', 'ठ', 'ड', 'ढ', 'ण',
                'त', 'थ', 'द', 'ध', 'न',
                'प', 'फ', 'ब', 'भ', 'म',
                'य', 'र', 'ल', 'व',
                'श', 'ष', 'स', 'ह',
                'ळ'
            ];
            const EXTRAS = 'क्ष त्र ज्ञ श्र ़ । ॥'.split(' ');
            const NUMBERS = '० १ २ ३ ४ ५ ६ ७ ८ ९'.split(' ');

            const editor = document.getElementById('editor');
            let savedSelection = null;

            function buildRow(chars, containerId) {{
                const container = document.getElementById(containerId);
                chars.forEach(char => {{
                    const btn = document.createElement('button');
                    btn.className = 'char-btn';
                    btn.textContent = char;
                    btn.onclick = () => insertText(char);
                    container.appendChild(btn);
                }});
            }}

            buildRow(VOWELS, 'vowels');
            buildRow(MATRAS, 'matras');
            buildRow(CONSONANTS, 'consonants-row');
            buildRow(EXTRAS, 'extras-row');
            buildRow(NUMBERS, 'numbers-row');

            function toggleSection(id) {{
                const section = document.getElementById(id);
                const toggle = document.getElementById(id + '-toggle');
                section.classList.toggle('open');
                toggle.textContent = section.classList.contains('open') ? '-' : '+';
            }}

            document.addEventListener('selectionchange', () => {{
                if (document.activeElement === editor) {{
                    const selection = window.getSelection();
                    if (selection.rangeCount > 0) {{
                        savedSelection = selection.getRangeAt(0).cloneRange();
                    }}
                }}
            }});

            function insertText(text) {{
                editor.focus();

                if (savedSelection) {{
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(savedSelection);
                }}

                const selection = window.getSelection();
                if (selection.rangeCount > 0) {{
                    const range = selection.getRangeAt(0);
                    range.deleteContents();
                    const textNode = document.createTextNode(text);
                    range.insertNode(textNode);
                    range.setStartAfter(textNode);
                    range.collapse(true);
                    selection.removeAllRanges();
                    selection.addRange(range);
                    savedSelection = range.cloneRange();
                }} else {{
                    editor.textContent += text;
                }}
            }}

            function copyText() {{
                const text = editor.innerText;
                navigator.clipboard.writeText(text).then(() => {{
                    document.getElementById('copyStatus').textContent = '✓ Copied! Now paste in the text box below and click Save';
                    document.getElementById('copyStatus').style.color = '#28a745';
                }}).catch(() => {{
                    // Fallback for older browsers
                    const textArea = document.createElement('textarea');
                    textArea.value = text;
                    document.body.appendChild(textArea);
                    textArea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textArea);
                    document.getElementById('copyStatus').textContent = '✓ Copied! Now paste in the text box below and click Save';
                    document.getElementById('copyStatus').style.color = '#28a745';
                }});
            }}
        </script>
    </body>
    </html>
    '''

    # Render the HTML component
    components.html(html_content, height=height, scrolling=True)

    # Return the session state value (will be updated by the text_area below)
    return st.session_state[state_key]
