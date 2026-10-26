#!/usr/bin/env python3
"""NOAA / NWS ground truth (I2, I3, I4, I5, I9).

  I2  NHC active storms JSON   https://www.nhc.noaa.gov/CurrentStorms.json (advisory number/time/winds)
  I3  NWS active alerts        https://api.weather.gov/alerts/active?zone=FLC033,FLZ201,FLZ202 (Escambia county + zones)
  I4  NWS latest observation   https://api.weather.gov/stations/KPNS/observations/latest
  I5  NWS active alerts        https://api.weather.gov/alerts/active?zone=ALC003,ALZ263,ALZ264,ALZ265,ALZ266
                               (Baldwin County AL; evacuation orders come from the county EMA - archived separately)
  I9  SPC storm reports CSV    https://www.spc.noaa.gov/climo/reports/today_hail.csv / yesterday_hail.csv (Texas rows)
api.weather.gov docs: https://www.weather.gov/documentation/services-web-api (User-Agent required)
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gt import Puller  # noqa: E402

NWS = "https://api.weather.gov"
H = {"Accept": "application/geo+json"}


def i2(out, hours=24):
    p = Puller("I2", out, hours)
    body = p.get("nhc_current_storms", "https://www.nhc.noaa.gov/CurrentStorms.json")
    for s in (body or {}).get("activeStorms", []):
        adv = s.get("publicAdvisory") or {}
        p.add(adv.get("url") or "https://www.nhc.noaa.gov/", f"{s.get('name')} ({s.get('classification')})",
              s.get("lastUpdate"), intensity_kt=s.get("intensity"), pressure_mb=s.get("pressure"),
              lat=s.get("latitudeNumeric"), lon=s.get("longitudeNumeric"), advisory=adv.get("advNum"),
              movement=f"{s.get('movementDir')} deg at {s.get('movementSpeed')} mph")
    if not p.items:
        p.notes.append("No active storms in CurrentStorms.json at pull time.")
    return p.save()


def _alerts(qid, out, zones, hours=24, note=""):
    p = Puller(qid, out, hours)
    body = p.get("nws_alerts_active", f"{NWS}/alerts/active", params={"zone": ",".join(zones)}, headers=H)
    for f in (body or {}).get("features", []):
        pr = f.get("properties", {})
        p.add(pr.get("@id") or f.get("id"), f"{pr.get('event')} - {pr.get('areaDesc')}", pr.get("sent"),
              event=pr.get("event"), severity=pr.get("severity"), onset=pr.get("onset"), expires=pr.get("expires"),
              headline=pr.get("headline"))
    p.notes.append(f"Active NWS alerts for zones {zones}. {note}".strip())
    if not p.items:
        p.notes.append("No active alerts at pull time => correct answer is 'none'.")
    return p.save()


def i3(out):
    return _alerts("I3", out, ["FLC033", "FLZ201", "FLZ202"])


def i5(out):
    return _alerts("I5", out, ["ALC003", "ALZ263", "ALZ264", "ALZ265", "ALZ266"],
                   note="Evacuation orders: look for event 'Evacuation Immediate' and check Baldwin County EMA (manual, archived).")


def i4(out, hours=1):
    p = Puller("I4", out, hours)
    body = p.get("kpns_latest_observation", f"{NWS}/stations/KPNS/observations/latest", headers=H)
    pr = (body or {}).get("properties", {})
    if pr:
        ws = (pr.get("windSpeed") or {}).get("value")
        wg = (pr.get("windGust") or {}).get("value")
        kmh_to_mph = lambda v: round(v * 0.621371, 1) if v is not None else None
        p.add(pr.get("@id") or f"{NWS}/stations/KPNS/observations/latest", pr.get("textDescription"), pr.get("timestamp"),
              wind_speed_kmh=ws, wind_speed_mph=kmh_to_mph(ws), wind_gust_kmh=wg, wind_gust_mph=kmh_to_mph(wg),
              wind_direction_deg=(pr.get("windDirection") or {}).get("value"))
    return p.save()


def i9(out, hours=24):
    p = Puller("I9", out, hours)
    for day in ("today", "yesterday"):
        txt = p.get(f"spc_{day}_hail", f"https://www.spc.noaa.gov/climo/reports/{day}_hail.csv", as_json=False)
        if not txt:
            continue
        for row in csv.DictReader(io.StringIO(txt)):
            if (row.get("State") or "").strip().upper() == "TX":
                p.add(f"https://www.spc.noaa.gov/climo/reports/{day}.html#{row.get('Time')}-{row.get('Location')}",
                      f"{row.get('Size')} hail at {row.get('Location')}, {row.get('County')} Co.", f"{day} {row.get('Time')}Z",
                      size_hundredths_in=row.get("Size"), county=row.get("County"), lat=row.get("Lat"), lon=row.get("Lon"))
    p.notes.append("SPC preliminary hail reports (12Z-12Z convective days); 'today'/'yesterday' are relative to SPC's day.")
    if not p.items:
        p.notes.append("No Texas hail reports => correct answer is 'none'.")
    return p.save()


def main(out):
    for f in (i2, i3, i4, i5, i9):
        try:
            f(out)
        except Exception as e:
            print(f"  {f.__name__} failed: {e!r}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
