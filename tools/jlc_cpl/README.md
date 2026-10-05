# JLC CPL rotation fix

KiCad and JLCPCB define 0° differently for many packages. A CPL that copies the KiCad rotations makes
JLC's placement preview show ICs and connectors turned by 90°, 180° or 270°. Through-hole parts are also
off-centre, because KiCad puts their origin on pin 1 and JLC puts it at the body centre.

This tool fixes both from JLC's own data. For every part in the JLC BOM it downloads the LCSC footprint
that JLC places from (EasyEDA Pro), matches its pads to the KiCad footprint, and finds the rotation
(0/90/180/270) and centroid offset that put JLC's part on the KiCad pads.

## Run

From this folder, after any layout change and before an order:

```
"C:\Users\Flow-Lab\AppData\Local\Programs\KiCad\10.0\bin\python.exe" kpads.py
node jlc_rot.js
```

1. `kpads.py` (KiCad's Python) exports each footprint's position, rotation and pads to `kpads.json`.
2. `jlc_rot.js` (Node 18+, curl on the path) writes `cpl_new.csv` and `rot_report.txt`.
3. Read `rot_report.txt`. Each line gives the correction, the new rotation, the centroid shift and the
   pad fit (worst pad-centre error). `<< CHECK` means a fit above 0.2 mm; on the `_HandSolder`
   footprints that is expected, because their pads are longer than JLC's.
4. Copy `cpl_new.csv` over `../../fab/jlc/PiDG_Pico_JLC_CPL.csv`.
5. Still look at JLC's placement preview before you approve the order.

Downloads are cached in `eda/` (git-ignored); delete it to fetch again. Some LCSC footprints are stored
encrypted (AES-256-GCM); the script decrypts them with the key that the same API response provides.
Parts with no LCSC footprint stay unchanged, except two-pad chip resistors and capacitors, which need
no correction. When pad numbers differ (for example the BNC posts), the match uses pad 1 and the pad
geometry.

**Body direction.** The script also compares where JLC's part body lies (its component-shape and pin
layers) with the KiCad body (courtyard). For pin headers and sockets, whose pins are all identical, JLC
sometimes numbers the pins in mirror order relative to the body (J16 and TP3 here); the pin-number match
then puts the body on the wrong side. For those parts the script uses the rotation that puts the body on
the KiCad body. For any other part with a body mismatch it reports `<< CHECK: JLC body ... from KiCad body`
and changes nothing.

## Conventions

- Rotation is counter-clockwise seen from the top, the same as KiCad. CPL rotation = KiCad rotation +
  correction.
- Mid Y is the negated KiCad Y, as in the existing CPL. Top side only.
