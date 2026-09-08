from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs

from moriarty.services.phone_analyzer import PhoneAnalyzer


def decode_qr_contacts(payload:bytes,analyzer:PhoneAnalyzer,default_region:str|None=None)->dict:
    try:
        from PIL import Image
        import zxingcpp
    except ImportError as exc:raise RuntimeError("QR support is unavailable; reinstall Moriarty dependencies.") from exc
    image=Image.open(BytesIO(payload));decoded=[]
    for barcode in zxingcpp.read_barcodes(image):
        text=str(barcode.text or "").strip()
        if text:decoded.append(parse_contact_payload(text,analyzer,default_region))
    return {"count":len(decoded),"contacts":tuple(decoded)}


def parse_contact_payload(text:str,analyzer:PhoneAnalyzer,default_region:str|None=None)->dict:
    clean=text.strip();fields={"raw":clean,"format":"text","name":"","organization":"","phones":[],"emails":[],"websites":[],"address":""}
    upper=clean.upper()
    if upper.startswith("BEGIN:VCARD"):
        fields["format"]="vcard";pairs=[]
        for line in clean.replace("\r\n","\n").split("\n"):
            if ":" in line:pairs.append(line.split(":",1))
        for key,value in pairs:
            base=key.split(";",1)[0].upper()
            if base in {"FN","N"} and not fields["name"]:fields["name"]=value.replace(";"," ").strip()
            elif base=="ORG":fields["organization"]=value.replace(";"," ").strip()
            elif base=="TEL":fields["phones"].append(value)
            elif base=="EMAIL":fields["emails"].append(value)
            elif base=="URL":fields["websites"].append(value)
            elif base=="ADR":fields["address"]=", ".join(part for part in value.split(";") if part)
    elif upper.startswith("MECARD:"):
        fields["format"]="mecard"
        for part in clean[7:].split(";"):
            if ":" not in part:continue
            key,value=part.split(":",1);key=key.upper()
            if key=="N":fields["name"]=value
            elif key=="ORG":fields["organization"]=value
            elif key=="TEL":fields["phones"].append(value)
            elif key=="EMAIL":fields["emails"].append(value)
            elif key=="URL":fields["websites"].append(value)
            elif key=="ADR":fields["address"]=value
    elif clean.lower().startswith("tel:"):fields["format"]="tel";fields["phones"].append(clean[4:])
    elif clean.lower().startswith("mailto:"):fields["format"]="mailto";fields["emails"].append(clean[7:].split("?",1)[0])
    normalized=[]
    for raw in fields.pop("phones"):
        try:phone=analyzer.analyze(raw,default_region);normalized.append({"raw":raw,"e164":phone.e164,"is_valid":phone.is_valid})
        except Exception:continue
    fields["phones"]=tuple(normalized);fields["emails"]=tuple(dict.fromkeys(fields["emails"]));fields["websites"]=tuple(dict.fromkeys(fields["websites"]))
    return fields


def read_image(value:str,timeout:float=15.0,max_bytes:int=5_000_000)->bytes:
    if value.startswith(("http://","https://")):
        from moriarty.services.web_page_verifier import load_public_binary
        return load_public_binary(value,timeout,max_bytes)[1]
    path=Path(value).expanduser()
    payload=path.read_bytes()
    if len(payload)>max_bytes:raise RuntimeError("QR image exceeds the configured size limit.")
    return payload
