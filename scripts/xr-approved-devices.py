#!/usr/bin/env python3
"""Intel XR approved-device registry.

Imports JSON or XLSX device lists, normalizes MAC addresses, and stores a local
registry. MAC membership is authorization evidence only after ALVR protocol
validation succeeds.
"""
import argparse, json, re
from pathlib import Path

DEFAULT=Path.home()/".config/intel-xr/approved-devices.json"
MAC=re.compile(r"^[0-9A-F]{12}$")

def norm(v):
    s=re.sub(r"[^0-9A-Fa-f]","",str(v or "")).upper()
    if not MAC.match(s): raise ValueError(f"invalid MAC address: {v!r}")
    return ":".join(s[i:i+2] for i in range(0,12,2))

def load_registry(path):
    if not path.exists(): return {"version":1,"devices":[]}
    return json.loads(path.read_text())

def rows_json(path):
    obj=json.loads(path.read_text())
    if isinstance(obj,dict): obj=obj.get("devices",obj.get("approved_devices",[]))
    if not isinstance(obj,list): raise ValueError("JSON must be an array or contain devices/approved_devices array")
    return obj

def rows_xlsx(path):
    from openpyxl import load_workbook
    ws=load_workbook(path,read_only=True,data_only=True).active
    it=ws.iter_rows(values_only=True); headers=[str(x or "").strip().lower() for x in next(it)]
    aliases={"mac":"mac_address","mac address":"mac_address","address":"mac_address","device":"name","device_name":"name"}
    headers=[aliases.get(h,h) for h in headers]
    return [dict(zip(headers,row)) for row in it if any(v is not None for v in row)]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("action",choices=["list","import","add","remove","check"])
    ap.add_argument("value",nargs="?"); ap.add_argument("--registry",default=str(DEFAULT)); ap.add_argument("--name",default="")
    a=ap.parse_args(); p=Path(a.registry); reg=load_registry(p)
    if a.action=="list": print(json.dumps(reg,indent=2)); return
    if a.action=="check":
        m=norm(a.value); hit=next((d for d in reg["devices"] if d["mac_address"]==m and d.get("enabled",True)),None)
        print(json.dumps({"mac_address":m,"approved":bool(hit),"device":hit},indent=2)); raise SystemExit(0 if hit else 1)
    if a.action=="remove":
        m=norm(a.value); reg["devices"]=[d for d in reg["devices"] if d["mac_address"]!=m]
    elif a.action=="add":
        incoming=[{"mac_address":a.value,"name":a.name,"enabled":True}]
    else:
        src=Path(a.value); incoming=rows_xlsx(src) if src.suffix.lower()==".xlsx" else rows_json(src)
    if a.action in ("add","import"):
        by={d["mac_address"]:d for d in reg["devices"]}
        for row in incoming:
            raw=row.get("mac_address",row.get("mac"))
            m=norm(raw)
            by[m]={"mac_address":m,"name":str(row.get("name","") or ""),"notes":str(row.get("notes","") or ""),"enabled":bool(row.get("enabled",True))}
        reg["devices"]=sorted(by.values(),key=lambda d:d["mac_address"])
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(reg,indent=2)+"\n")
    print(f"Saved {len(reg['devices'])} approved device(s) to {p}")
if __name__=="__main__": main()
