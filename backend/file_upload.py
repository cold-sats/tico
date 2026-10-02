"""Incremental multipart parsing: bounded fields and private, short-lived disk spools."""
import tempfile
from contextlib import ExitStack

from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header

from .store import Problem


async def parse(request, limit, directory):
    _, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if not boundary or len(boundary) > 200:
        raise Problem("validation", "Multipart upload needs a valid boundary", 422)
    try:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError:
        raise Problem("blob_storage", "Upload staging is unavailable; check disk space and permissions", 503, True) from None
    stack = ExitStack()
    fields, files, part, headers = {}, {}, {}, {}
    finished = False
    def fail(detail):
        raise Problem("validation", detail, 422)
    def begin():
        part.clear()
        headers.clear()
        part.update(header_name=bytearray(), header_value=bytearray(), data=bytearray(), size=0)
    def header_field(data, start, end):
        part["header_name"].extend(data[start:end])
        if len(part["header_name"]) > 1024:
            fail("Upload header is too long")
    def header_value(data, start, end):
        part["header_value"].extend(data[start:end])
        if len(part["header_value"]) > 4096:
            fail("Upload header is too long")
    def header_end():
        headers[bytes(part["header_name"]).lower()] = bytes(part["header_value"])
        part["header_name"].clear()
        part["header_value"].clear()
    def headers_done():
        _, opts = parse_options_header(headers.get(b"content-disposition", b""))
        name = opts.get(b"name", b"").decode("utf-8")
        part["name"] = name
        if name in fields or name in files:
            fail("Duplicate upload field")
        if b"filename" in opts:
            if name not in ("file", "poster"):
                fail("Use the file and optional poster fields")
            part["stream"] = stack.enter_context(tempfile.TemporaryFile(dir=directory))
            part["filename"] = opts[b"filename"].decode("utf-8")
            part["mime"] = headers.get(b"content-type", b"application/octet-stream").decode("ascii")
        elif name not in ("name", "note", "ask"):
            fail("Unknown upload field")
    def data(data, start, end):
        chunk = data[start:end]
        part["size"] += len(chunk)
        maximum = limit if part["name"] == "file" else 10_000_000 if "stream" in part else 64_000
        if part["size"] > maximum:
            raise Problem("too_large", f"{part['name']} exceeds the upload limit of {maximum} bytes", 413)
        if "stream" in part:
            part["stream"].write(chunk)
        else:
            part["data"].extend(chunk)
    def end():
        name = part["name"]
        if "stream" in part:
            if part["size"] == 0:
                fail("A file must contain at least one byte")
            part["stream"].seek(0)
            files[name] = {k: part[k] for k in ("stream", "filename", "mime", "size")}
        else:
            fields[name] = part["data"].decode("utf-8")
    def complete():
        nonlocal finished
        finished = True
    parser = MultipartParser(boundary, {"on_part_begin": begin, "on_header_field": header_field,
        "on_header_value": header_value, "on_header_end": header_end, "on_headers_finished": headers_done,
        "on_part_data": data, "on_part_end": end, "on_end": complete})
    try:
        async for chunk in request.stream():
            parser.write(chunk)
        parser.finalize()
        if not finished or "file" not in files:
            fail("Send a complete multipart upload with a file field")
        return fields, files, stack
    except BaseException as exc:
        stack.close()
        if isinstance(exc, OSError):
            raise Problem("blob_storage", "Upload staging failed; free disk space and retry", 503, True) from None
        if isinstance(exc, (ValueError, UnicodeError)):
            raise Problem("validation", "Malformed multipart upload", 422) from None
        raise
