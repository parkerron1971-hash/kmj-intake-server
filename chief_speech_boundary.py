"""Keep authoring scaffolding out of Chief's spoken conversation.

This is separate from factual review: an instruction can contain no false
facts and still be the wrong thing to say. Check whole sentences before
release, so provider token boundaries cannot leak the start of a directive.
Business rules and policy discussion are not themselves internal content.
"""
from __future__ import annotations

import re
import json
import logging

_END = re.compile(r'(?<=[.!?])["\u201d\u2019)]?\s+|\n+')
_MARKER = re.compile(
    r'\[\[CHIEF_(?:GLOBAL|CACHE|TURN)_SPLIT\]\]|'
    r'\[\s*SYSTEM\s+(?:REMINDER|CORRECTION)\b|'
    r'\bSYSTEM\s+(?:REMINDER|CORRECTION)\s*:|'
    r'<\s*/?\s*(?:analysis|thinking|system)\s*>|'
    r'\b(?:the headline is already said|silent narration|'
    r'prior assistant prose is not proof|new operations require a tool call)\b', re.I)
_PRIVATE_BLOCK = re.compile(
    r'<\s*(analysis|thinking|system)\s*>.*?(?:<\s*/\s*\1\s*>|$)|'
    r'\[\s*SYSTEM\s+(?:REMINDER|CORRECTION)\b[^\]]*(?:\]|$)|'
    # Without a closing delimiter there is no reliable end to a correction.
    # Keep preceding answer text, but do not guess where private prose ends.
    r'\bSYSTEM\s+(?:REMINDER|CORRECTION)\s*:.*$', re.I | re.S)
_OWN_RULES = re.compile(
    r'\b(?:(?:I|we) (?:must|should|need to|have to|am instructed to|are instructed to)\b[^.!?\n]{0,160}'
    r'\b(?:system|developer|internal) (?:instructions?|rules?|prompt)|'
    r'my (?:system|developer|internal) (?:instructions?|rules?|prompt)|'
    r'(?:according to|following|under|per) (?:my |the )?(?:system|developer|internal) '
    r'(?:instructions?|rules?|prompt))\b', re.I)
_DIRECTIVE = re.compile(
    r'^\s*(?:[-*>#\d.)\s]+)?(?:'
    r'(?:keep|make) (?:the|your|this) (?:response|reply|answer) '
    r'(?:brief|short|concise|conversational)|'
    r'(?:do not|never|don\x27t) (?:narrate|reveal|mention|repeat|expose) '
    r'(?:the |your |these |this )?(?:internal|system|developer|instructions|rules)|'
    r'(?:do not|never|don\x27t) emit (?:any )?(?:action )?tags in (?:this|the|your) reply|'
    r'you are (?:the )?Chief(?:,|\b replying)|'
    r'(?:for this turn,? )?use only the (?:supplied|provided) evidence|'
    r'(?:respond|reply|answer) (?:in|with) (?:one|two|three|a single|short) '
    r'(?:short |concise )?sentences?|'
    r'(?:continue|begin) (?:directly |straight )?(?:with|from) '
    r'(?:the (?:answer|next sentence)|what (?:they|the user) need)|'
    r'(?:the )?user (?:is asking|wants) .{0,100}\b(?:I should|I need to|we should)'
    r')\b', re.I)
_WRITING_REQUEST = re.compile(
    r'\b(?:write|draft|edit|rewrite|review|explain|discuss|translate|quote|read)\b'
    r'.{0,100}\b(?:prompt|instructions?|response guidelines|writing rules|system message)\b|'
    r'\b(?:what|how)\b.{0,70}\b(?:system prompts?|prompt writing)\b|'
    r'\b(?:how (?:should|do|can) I|what should I|help me) '
    r'(?:reply|respond|say|tell|write)\b|'
    r'\b(?:write|draft|edit|rewrite|review)\b.{0,80}'
    r'\b(?:reply|response|email|message|letter)\b', re.I)

UNAVAILABLE_REPLY = "I couldn't finish that answer. Please try again."


def note_block(stage: str, *, request_id=None) -> None:
    """Correlate the stage with the turn; never record generated prose."""
    import chief_request_timing
    trace = chief_request_timing.CURRENT.get()
    logging.getLogger('chief.speech_boundary').warning(
        '[chief speech boundary] %s', json.dumps({
            'request_id': str(request_id or (trace.request_id if trace else ''))[:80],
            'stage': stage[:40],
        }, separators=(',', ':')))


def internal_scaffolding(text: str, message: str = '') -> bool:
    """Recognize narrow authoring echoes, not any mention of rules/policies.

    Requested prompt writing can quote instructions. Runtime delimiters and
    handoff markers remain private even during that discussion.
    """
    text = str(text or '')
    if _MARKER.search(text):
        return True
    if _WRITING_REQUEST.search(str(message or '')):
        return False
    return bool(_OWN_RULES.search(text) or _DIRECTIVE.search(text))


def clean_reply(text: str, message: str = '') -> str:
    """Remove authoring sentences, retaining the answer's order and spacing."""
    text = str(text or '')
    text = _PRIVATE_BLOCK.sub('', text)
    parts, start = [], 0
    for end in _END.finditer(text):
        sentence = text[start:end.end()]
        if not internal_scaffolding(sentence, message):
            parts.append(sentence)
        start = end.end()
    tail = text[start:]
    if not internal_scaffolding(tail, message):
        parts.append(tail)
    return ''.join(parts).strip()


def final_reply(text: str, message: str = '', *, request_id=None) -> str:
    cleaned = clean_reply(text, message)
    if cleaned != str(text or '').strip():
        note_block('final', request_id=request_id)
    return cleaned or (UNAVAILABLE_REPLY if text and text.strip() else '')


class SentenceBoundary:
    """Buffer model prose until each sentence can pass the same hard gate."""
    def __init__(self, message: str = '', *, stage: str = 'model', request_id=None):
        self.message = message
        self.stage = stage
        self.request_id = request_id
        self.pending = ''
        self.blocked = False

    def feed(self, piece: str, *, final: bool = False) -> str:
        if self.blocked:
            return ''
        self.pending += piece
        out = []
        while self.pending:
            end = _END.search(self.pending)
            if not end and not final:
                if len(self.pending) > 12000:
                    self.blocked = True
                    self.pending = ''
                break
            cut = end.end() if end else len(self.pending)
            sentence, self.pending = self.pending[:cut], self.pending[cut:]
            if internal_scaffolding(sentence, self.message):
                note_block(self.stage, request_id=self.request_id)
                self.blocked = True
                self.pending = ''
                break
            out.append(sentence)
        return ''.join(out)
