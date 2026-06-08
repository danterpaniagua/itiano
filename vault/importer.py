import xml.etree.ElementTree as ET


def parse_kdbx(file, password=None):
    from pykeepass import PyKeePass
    kp = PyKeePass(file, password=password or None)
    entries = []
    for entry in kp.entries:
        entries.append({
            'name': entry.title or '',
            'url': entry.url or '',
            'username': entry.username or '',
            'password': entry.password or '',
            'notes': entry.notes or '',
            'tags': list(entry.tags or []),
        })
    return entries


def parse_xml(file):
    tree = ET.parse(file)
    root = tree.getroot()
    entries = []
    for entry in root.iter('Entry'):
        fields = {}
        for string in entry.findall('String'):
            key = string.findtext('Key', '')
            value = string.findtext('Value', '')
            fields[key] = value
        name = fields.get('Title', '').strip()
        if not name:
            continue
        tag_text = fields.get('Tags', '')
        tags = [t.strip() for t in tag_text.split(';') if t.strip()] if tag_text else []
        entries.append({
            'name': name,
            'url': fields.get('URL', ''),
            'username': fields.get('UserName', ''),
            'password': fields.get('Password', ''),
            'notes': fields.get('Notes', ''),
            'tags': tags,
        })
    return entries
