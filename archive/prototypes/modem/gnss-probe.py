#!/usr/bin/env python3
"""Throwaway: start a GNSS session on the modem's QMI LOC service (QRTR node 3) and print what it reports.
usage: gnss-probe.py [seconds]"""
import sys

import gi

gi.require_version("Qmi", "1.0")
gi.require_version("Qrtr", "1.0")
from gi.repository import GLib, Qmi, Qrtr  # noqa: E402

SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 60
loop = GLib.MainLoop()
keep = []  # the bus, node, device and client: freed objects close the QRTR socket (the modem drops the session)
counts = {"nmea": 0, "pos": 0, "sv": 0}


def fail(what, e):
    print(f"{what}: {e}", flush=True)
    loop.quit()


def on_nmea(_c, out):
    counts["nmea"] += 1
    s = out.get_nmea_string().strip()
    if s.startswith(("$GPGGA", "$GNGGA", "$GPGSV", "$GLGSV", "$GAGSV", "$GBGSV", "$GPRMC", "$GNRMC")) or counts["nmea"] < 6:
        print(s, flush=True)


def on_pos(_c, out):
    counts["pos"] += 1
    ok, st = out.get_session_status()
    lat = out.get_latitude()[1] if out.get_latitude()[0] else None
    lon = out.get_longitude()[1] if out.get_longitude()[0] else None
    print(f"position report: status {st if ok else '?'} lat {lat} lon {lon}", flush=True)


def on_sv(_c, out):
    counts["sv"] += 1
    ok, lst = out.get_list()
    n = len(lst) if ok and lst else 0
    print(f"sv info: {n} satellites listed", flush=True)


def on_ind(c, out, sig):
    """Every other indication: its status and readable fields."""
    vals = []
    for name in dir(out):
        if name.startswith("get_") and name not in ("get_type",):
            try:
                r = getattr(out, name)()
                vals.append(f"{name[4:]}={r[1] if isinstance(r, tuple) and len(r) > 1 else r}")
            except Exception:  # noqa: BLE001
                pass
    print(f"indication {sig}: {' '.join(vals)}", flush=True)
    if sig == "inject-time-request":
        import time
        i = Qmi.MessageLocInjectUtcTimeInput.new()
        i.set_utc_time(int(time.time() * 1000))
        i.set_time_uncertainty(1000)
        c.inject_utc_time(i, 10, None, lambda c, r: print("time injected", flush=True))


def lock_ready(c, res):
    try:
        c.get_engine_lock_finish(res)
    except Exception as e:  # noqa: BLE001
        print(f"get engine lock: {e}", flush=True)


def started(c, res):
    try:
        c.start_finish(res)
        print("session started", flush=True)
        c.get_engine_lock(None, 10, None, lock_ready)
    except Exception as e:  # noqa: BLE001
        fail("start", e)


def nmea_set(c, res):
    try:
        c.set_nmea_types_finish(res)
    except Exception as e:  # noqa: BLE001
        print(f"set nmea types: {e}", flush=True)
    i = Qmi.MessageLocStartInput.new()
    i.set_session_id(1)
    i.set_fix_recurrence_type(Qmi.LocFixRecurrenceType.PERIODIC_FIXES)
    i.set_intermediate_report_state(Qmi.LocIntermediateReportState.ENABLE)
    i.set_minimum_interval_between_position_reports(1000)
    c.start(i, 10, None, started)


def registered(c, res):
    try:
        c.register_events_finish(res)
    except Exception as e:  # noqa: BLE001
        return fail("register events", e)
    i = Qmi.MessageLocSetNmeaTypesInput.new()
    i.set_nmea_types(Qmi.LocNmeaType.GGA | Qmi.LocNmeaType.RMC | Qmi.LocNmeaType.GSV | Qmi.LocNmeaType.GSA)
    c.set_nmea_types(i, 10, None, nmea_set)


def got_client(dev, res):
    try:
        c = dev.allocate_client_finish(res)
        keep.append(c)
    except Exception as e:  # noqa: BLE001
        return fail("allocate client", e)
    c.connect("nmea", on_nmea)
    c.connect("position-report", on_pos)
    c.connect("gnss-sv-info", on_sv)
    for sig in ("set-nmea-types", "engine-state", "get-engine-lock", "set-engine-lock", "inject-time-request",
                "inject-position-request", "inject-utc-time", "set-operation-mode", "fix-recurrence-type"):
        c.connect(sig, on_ind, sig)
    i = Qmi.MessageLocRegisterEventsInput.new()
    f = Qmi.LocEventRegistrationFlag
    i.set_event_registration_mask(f.POSITION_REPORT | f.NMEA | f.GNSS_SATELLITE_INFO | f.ENGINE_STATE
                                  | f.FIX_SESSION_STATE | f.INJECT_TIME_REQUEST | f.INJECT_POSITION_REQUEST)
    c.register_events(i, 10, None, registered)


def opened(dev, res):
    try:
        dev.open_finish(res)
    except Exception as e:  # noqa: BLE001
        return fail("open", e)
    dev.allocate_client(Qmi.Service.LOC, Qmi.CID_NONE, 10, None, got_client)


def device(_s, res):
    try:
        dev = Qmi.Device.new_from_node_finish(res)
        keep.append(dev)
    except Exception as e:  # noqa: BLE001
        return fail("device", e)
    dev.open(Qmi.DeviceOpenFlags.AUTO, 10, None, opened)


def node(bus, res):
    try:
        n = bus.wait_for_node_finish(res)
        keep.append(n)
    except Exception as e:  # noqa: BLE001
        return fail("node", e)
    Qmi.Device.new_from_node(n, None, device)


def bus_ready(_s, res):
    try:
        bus = Qrtr.Bus.new_finish(res)
        keep.append(bus)
    except Exception as e:  # noqa: BLE001
        return fail("bus", e)
    bus.wait_for_node(3, 5000, None, node)


Qrtr.Bus.new(1000, None, bus_ready)
GLib.timeout_add_seconds(SECS, loop.quit)
loop.run()
# stop cleanly: the modem keeps a session of a vanished client running otherwise
print(f"done: {counts}", flush=True)
