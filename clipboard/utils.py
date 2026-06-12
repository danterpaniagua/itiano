from notes.models import Note


CLIPBOARD_NOTE_TITLE = 'Clipboard'


def get_or_create_clipboard_note(user):
    note = Note.objects.filter(owner=user, is_system=True).first()
    if note:
        return note

    # First access — migrate existing clipboard content if any
    body = ''
    try:
        entry = user.clipboard
        body = entry.get_decrypted()
    except Exception:
        pass

    return Note.objects.create(
        owner=user,
        title=CLIPBOARD_NOTE_TITLE,
        body=body,
        is_system=True,
    )
