# GNSS (GPS) on the nio

**Status (2026-10-27): the engine runs on the host; no fix tested yet (indoors), no service, no handle.**

## Where it is
The GNSS engine is in the SDX55 modem (the SM8250 has no modem of its own), offered as QMI LOC (service 16, v2) on
QRTR node 3, next to the services `mship-modem` already uses. Its RF path is the modem's SDR865
(`rfc_card_gnss.cpp: GNSS L1 sig path is 247`); nothing on the host side (no regulator, GPIO or DT node) is needed.

## What it takes (found 2026-10-27 with the modem's F3 log)
1. **Unlock the engine.** It ships locked for mobile- and network-initiated sessions (`tm_pdapi_iface.c: MI GPS is
   locked`, lock type 3): every session is ended at once. Stock Android clears it at boot (gps.conf `GPS_LOCK`).
   `QMI LOC Set Engine Lock` = none (`qmicli -d qrtr://3 --loc-set-engine-lock=none`). Whether it persists over a
   modem restart is not checked yet: the service sets it at every start anyway.
2. **One client for the whole session.** LOC is per client; a QRTR client ends with its socket (the modem logs
   `locQmiShimClientDisconnectCb` and stops the fix). Register events (position report, NMEA, satellite info, engine
   state, inject-time request), set NMEA types (GGA, RMC, GSA, GSV), start (periodic, 1000 ms) in one process.
3. **Answer the time request.** The engine asks for UTC (`inject-time-request`, time.xtracloud.net): inject the
   host's clock (Inject UTC Time). Results of LOC requests come as indications, not in the response.

With these, a 2-minute session indoors: engine on, 836 NMEA sentences, 13 GPS satellites listed (from almanac, no
signal), 120 position reports without a fix. XTRA (predicted orbits) is not set up (`loc_xtra: Error 14346`): cold
starts take minutes without it.

## Tools
`motorola_nio/archive/prototypes/modem/`: `gnss-probe.py` (the session above, libqmi GI), `f3log.py` + `f3dec.py` (the modem's F3
log, decoded with `image/sdx55/qdsp6m.qdb` from the stock `modem_a` partition: zlib from offset 0x40; QShrink-4
packets: cmd 0x99, hash at offset 12, args from 18, byte 2 = count << 4 | size).

## Plan
1. Location client in `mship-modem` (QMI LOC over QRTR: unlock, time injection, NMEA/position stream), contract
   `mship.gnss`, handover item "location" (one VM at a time).
2. Ubuntu: NMEA into the guest (virtio console), gpsd or GeoClue.
3. Android: Cuttlefish's GNSS HAL already reads location from the host over a virtual console: feed it real NMEA.
4. XTRA download for fast fixes.
