"""Attachment names are labels, never filesystem paths or executable previews."""
import unicodedata
from pathlib import PurePosixPath
from fastapi import HTTPException


def attachment_name(value):
    if not isinstance(value,str) or not value.strip():
        raise HTTPException(422,'請提供附件檔名')
    if any(unicodedata.category(c) in ('Cc','Cf','Cs') for c in value):
        raise HTTPException(422,'附件檔名不可包含隱藏或方向控制字元')
    name=unicodedata.normalize('NFC',value.replace('\\','/').split('/')[-1]).strip()
    if not name or len(name)>180 or name.endswith(('.', ' ')) or ':' in name:
        raise HTTPException(422,'附件檔名不合法或超過180字')
    if PurePosixPath(name).suffix.lower() in {'.exe','.com','.bat','.cmd','.ps1','.vbs',
            '.vbe','.js','.jse','.scr','.msi','.msp','.lnk','.url','.hta','.reg'}:
        raise HTTPException(422,'不接受可執行程式或系統捷徑附件')
    return name
