"""Streaming local files and explicit resource budgets for research execution.

No network access, automatic expansion of budgets, or implicit raw-data upload.
"""
import hashlib
import os
from pathlib import Path
import shutil
import stat

from .artifacts import confined
from .core import ValidationError

MIB = 1024 ** 2
CHUNK = MIB


def validate_resources(value):
    bounds = {'input_bytes': (1, 16 * 1024**4), 'output_bytes': (1, 16 * 1024**4),
              'file_bytes': (1, 16 * 1024**4), 'reserve_bytes': (0, 16 * 1024**4)}
    if not isinstance(value, dict) or set(value) != set(bounds):
        raise ValidationError('Resources need input_bytes/output_bytes/file_bytes/reserve_bytes')
    for key, (lo, hi) in bounds.items():
        if type(value[key]) is not int or not lo <= value[key] <= hi:
            raise ValidationError('Invalid resource budget: ' + key)
    if value['file_bytes'] > value['output_bytes']:
        raise ValidationError('Per-file output budget exceeds total output budget')
    return value


def regular(path, maximum):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, 'st_file_attributes', 0) & 0x400 or info.st_size > maximum):
        raise ValidationError('Expected a regular unlinked file within the declared byte budget: ' + str(path))
    return info


def disk_preflight(directory, required, reserve=0):
    path = Path(directory).resolve()
    while not path.exists():
        path = path.parent
    if shutil.disk_usage(path).free < required + reserve:
        raise ValidationError('Insufficient free disk for declared staging/output budgets and reserve')


def stream_file(source, *, expected=None, target=None, maximum, reserve=0):
    """Hash the very bytes copied; reject growth, replacement and in-place drift.

    Target is exclusively created and removed on failure. Caller owns its parent.
    A hash is an integrity commitment, not authentication or scientific validity.
    """
    source = Path(source)
    before = regular(source, maximum)
    destination = Path(target) if target is not None else None
    digest, size, created = hashlib.sha256(), 0, False
    def identity(s):
        # Windows path stat and fstat disagree on ctime semantics (birth/change
        # time). File identity, size, mtime and the pinned hash are portable.
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    try:
        with source.open('rb') as reader:
            if identity(os.fstat(reader.fileno())) != identity(before):
                raise ValidationError('Source changed while opening')
            writer = destination.open('xb') if destination is not None else None
            created = writer is not None
            try:
                while block := reader.read(CHUNK):
                    size += len(block)
                    if size > maximum:
                        raise ValidationError('File grew beyond declared byte budget')
                    digest.update(block)
                    if writer is not None:
                        disk_preflight(destination.parent, len(block), reserve)
                        writer.write(block)
                if identity(os.fstat(reader.fileno())) != identity(before):
                    raise ValidationError('Source changed while streaming')
            finally:
                if writer is not None:
                    writer.close()
        if identity(regular(source, maximum)) != identity(before):
            raise ValidationError('Source replaced while streaming')
        if expected is not None and digest.hexdigest() != expected:
            raise ValidationError('Pinned file changed: ' + source.name)
        return {'sha256': digest.hexdigest(), 'bytes': size}
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def inventory_pinned(root, files, maximum):
    total, inventory = 0, {}
    for name, digest in files.items():
        path = confined(root, name)
        row = stream_file(path, expected=digest, maximum=maximum - total)
        total += row['bytes']
        inventory[name] = row
    return inventory
