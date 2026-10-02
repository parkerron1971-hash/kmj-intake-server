"""Exact call feedback is not a request to revisit business records."""
import re


def reply_for(message, *, voice=False):
    text = re.sub(r"[^\w\s]", " ", str(message or '').casefold())
    text = ' '.join(text.split())
    # A recognizer endpoint can split a thinking pause into a whole turn.
    # Only exact voice hesitations/incomplete wording qualify: short answers,
    # names, other languages, and any additional request keep the normal path.
    if voice and text in {'um', 'uh', 'erm', 'hmm'}:
        return "Take your time."
    if voice and text == 'this is':
        return "I'm listening."
    if text in {'you can hear the background too', 'you are picking up background noise',
                'you re picking up background noise', 'you picked up background speech'}:
        return ("Thanks for flagging that. Background speech may be getting picked up; "
                "please repeat anything the transcript got wrong.")
    if text in {'okay i heard it twice', 'i heard it twice', 'i heard that twice',
                'you said that twice', 'i hear you twice'}:
        return "Thanks for flagging the repeated audio. What would you like me to help with next?"
    if text in {'can you hear me', 'did you hear me', 'can you hear what i just said'}:
        return "I'm here. Your message came through."
    if text in {'let me end that one', 'stop talking', 'please stop talking', 'stop speaking'}:
        # Acknowledge the pause without pretending to disconnect the call.
        return "Okay."
    if voice and text == 'dobrý den':
        return "Dobrý den! Jak vám mohu pomoci?"
    return None


def for_request(req):
    if getattr(req, 'image_ids', None) or (getattr(req, 'mode', None) or '') not in ('', 'chief'):
        return None
    return reply_for(getattr(req, 'message', ''),
                     voice=getattr(req, 'client_surface', '') == 'voice')
