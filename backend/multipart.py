"""قراءة multipart/form-data من غير أي مكتبة إضافية — نصوص + ملفات شكلها {name: (filename, blob)}."""
from email.parser import BytesParser
from email.policy import HTTP


def parsemultipart(content_type, raw):
    fields, files = {}, {}
    if "boundary=" not in content_type:
        return fields, files
    head = ("Content-Type: %s\r\nMIME-Version: 1.0\r\n\r\n" % content_type).encode("latin-1", "replace")
    try:
        msg = BytesParser(policy=HTTP).parsebytes(head + raw)
    except Exception:
        return fields, files
    if not msg.is_multipart():
        return fields, files
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        blob = part.get_payload(decode=True) or b""
        if part.get_filename() is not None:
            files[name] = (part.get_filename() or "", blob)
        else:
            fields[name] = blob.decode(part.get_content_charset() or "utf-8", "replace")
    return fields, files
