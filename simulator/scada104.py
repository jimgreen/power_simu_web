"""Run an independent scdfe_s Web/IEC104 process backed by simulator models."""

import argparse
import json
import logging
import math
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.request import Request, urlopen


LOG = logging.getLogger("simulator.scada104")
KINDS = ("yc", "yx", "yk", "yt")
DATABASE = Path(r"D:\codex\workspace\simulation\qinling\simulator\simulator\scdfe_s.sqlite3")


def port_available(port):
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def request(base, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(base + path, body, {"Content-Type": "application/json"})
    with urlopen(req, timeout=3) as response:
        return json.load(response)


def read_points(base):
    measurement = request(base, "/api/measurements")
    controls = request(base, "/api/external/controls/names")
    definitions = {kind: {} for kind in KINDS}
    values = {str(row["name"]): row for row in measurement["scada"]}
    for row in measurement["definitions"]:
        kind = "yx" if str(row["meas_type"]).upper() in {"RUN_STAT", "STATUS"} else "yc"
        definitions[kind][str(row["name"])] = values.get(str(row["name"]))
    for kind in ("yk", "yt"):
        definitions[kind].update((name, None) for name in controls[kind + "_names"])
    return definitions


class Bridge:
    def __init__(self, server, simulator_url, first_port):
        self.server = server
        self.simulator_url = simulator_url
        self.first_port = first_port
        self.stop = threading.Event()
        self.online = {}
        self.initialized = set()
        self.pending_reload = set()
        self.last_errors = {}
        with server.store.connection() as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS simulator104_models (
                model TEXT PRIMARY KEY, rtu_id INTEGER UNIQUE NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS simulator104_points (
                rtu_id INTEGER NOT NULL, kind TEXT NOT NULL, source_name TEXT NOT NULL,
                pnt_no INTEGER NOT NULL, active INTEGER NOT NULL,
                PRIMARY KEY (rtu_id, kind, source_name), UNIQUE (rtu_id, kind, pnt_no))""")

    def channel(self, model):
        store = self.server.store
        with store.connection() as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT rtu_id FROM simulator104_models WHERE model=?", (model,)).fetchone()
            if row:
                return int(row[0])
            used = {int(value) for value, in db.execute(
                "SELECT rtu_id FROM fes_rtu_define UNION SELECT channel_id FROM fes_rtu_define "
                "UNION SELECT channel_id FROM fes_channel_iec104_define "
                "UNION SELECT rtu_id FROM simulator104_models"
            ) if value is not None}
            ports = {int(port) for port, in db.execute(
                "SELECT remote_port FROM fes_channel_iec104_define WHERE remote_port IS NOT NULL")}
            rtu = next(number for number in range(1, 65535) if number not in used)
            port = next(number for number in range(self.first_port, 65536)
                        if number not in ports and port_available(number))
            db.execute("INSERT INTO fes_channel_iec104_define (channel_id,rtu_addr,remote_port) VALUES (?,?,?)",
                       (rtu, rtu, port))
            db.execute("INSERT INTO fes_rtu_define (rtu_id,channel_id,channel_type,name) VALUES (?,?,'iec104',?)",
                       (rtu, rtu, model))
            db.execute("INSERT INTO simulator104_models VALUES (?,?)", (model, rtu))
        return rtu

    def sync_points(self, rtu, points):
        now = time.time_ns() // 1_000_000
        changed = False
        with self.server.store.connection() as db, db:
            db.execute("BEGIN IMMEDIATE")
            for kind, current in points.items():
                table = f"fes_{kind}_define"
                known = {name: (no, active) for name, no, active in db.execute(
                    "SELECT source_name,pnt_no,active FROM simulator104_points WHERE rtu_id=? AND kind=?",
                    (rtu, kind))}
                existing = {no: (value, status) for no, value, status in db.execute(
                    f"SELECT pnt_no,value,status FROM {table} WHERE rtu_id=?", (rtu,))}
                number = max([0, *existing, *(entry[0] for entry in known.values())])
                for name, row in current.items():
                    if name not in known:
                        number += 1
                        db.execute(f"INSERT INTO {table} (rtu_id,pnt_no,name,value,status) VALUES (?,?,?,0,128)",
                                   (rtu, number, name))
                        db.execute("INSERT INTO simulator104_points VALUES (?,?,?,?,1)", (rtu, kind, name, number))
                        known[name] = (number, True)
                        existing[number] = (0, 128)
                        changed = True
                    no, active = known[name]
                    if not active:
                        db.execute("UPDATE simulator104_points SET active=1 WHERE rtu_id=? AND kind=? AND source_name=?",
                                   (rtu, kind, name))
                    if kind in {"yc", "yx"} and no in existing:
                        value = row.get("value") if row else None
                        valid = isinstance(value, (int, float)) and math.isfinite(value) and bool(row.get("valid", 1))
                        if kind == "yx":
                            valid = valid and value in (0, 1)
                        previous, status = existing[no]
                        quality = 0 if valid else 128
                        value = value if valid else previous
                        if (value, quality) != (previous, status):
                            db.execute(f"UPDATE {table} SET value=?,status=?,refresh_time=? WHERE rtu_id=? AND pnt_no=?",
                                       (value, quality, now, rtu, no))
                for name, (no, active) in known.items():
                    if active and name not in current:
                        db.execute("UPDATE simulator104_points SET active=0 WHERE rtu_id=? AND kind=? AND source_name=?",
                                   (rtu, kind, name))
                        db.execute(f"UPDATE {table} SET status=128,refresh_time=? WHERE rtu_id=? AND pnt_no=?",
                                   (now, rtu, no))
        return changed

    def execute(self, rtu, kind, number, value):
        if kind not in {"yk", "yt"}:
            raise ValueError("只允许遥控或遥调")
        with self.server.store.connection() as db:
            row = db.execute(
                f"SELECT b.source_name,p.man_disable,p.auto_disable FROM simulator104_points b "
                f"JOIN fes_{kind}_define p ON p.rtu_id=b.rtu_id AND p.pnt_no=b.pnt_no "
                "WHERE b.rtu_id=? AND b.kind=? AND b.pnt_no=? AND b.active=1",
                (rtu, kind, number)).fetchone()
        base = self.online.get(rtu)
        if row is None or base is None:
            raise ValueError("仿真控制点未绑定、已退役或模型离线")
        if row[1] or row[2]:
            raise ValueError("控制点已禁止操作")
        if value is None or not math.isfinite(float(value)) or (kind == "yk" and value not in (0, 1)):
            raise ValueError("无效遥控或遥调值")
        response = request(base, "/api/external/controls/execute",
                           {kind + "_names": [row[0]], kind + "_values": [value], "source": "scdfe_s"})
        key = "remote_controls" if kind == "yk" else "remote_adjustments"
        if response.get("accepted", {}).get(key) != 1:
            raise ValueError("仿真模型未接受该指令")

    def poll(self):
        while not self.stop.is_set():
            seen = set()
            try:
                for model in request(self.simulator_url, "/api/models")["models"]:
                    service = model.get("service") or {}
                    if not service.get("healthy"):
                        continue
                    name, base = model["id"], service["base_url"]
                    try:
                        points = read_points(base)
                        rtu = self.channel(name)
                        changed = self.sync_points(rtu, points)
                        self.online[rtu] = base
                        seen.add(rtu)
                        channel = self.server.channel_services(rtu_id=rtu)[f"iec104-rtu-{rtu}"]
                        if rtu not in self.initialized or (changed and channel.status()["running"]):
                            self.pending_reload.add(rtu)
                        if rtu in self.pending_reload:
                            if channel.status()["running"]:
                                channel.stop()
                            channel.start()
                            self.pending_reload.remove(rtu)
                            self.initialized.add(rtu)
                        self.last_errors.pop(name, None)
                    except Exception as exc:
                        self.report_error(name, exc)
                self.last_errors.pop("catalog", None)
            except Exception as exc:
                self.report_error("catalog", exc)
            for rtu in self.online.keys() - seen:
                self.online.pop(rtu, None)
                with self.server.store.connection() as db, db:
                    for kind in ("yc", "yx"):
                        db.execute(f"UPDATE fes_{kind}_define SET status=128 WHERE rtu_id=? AND status IS NOT 128", (rtu,))
            self.stop.wait(1)

    def report_error(self, name, exc):
        if self.last_errors.get(name) != str(exc):
            LOG.error("%s: %s", name, exc)
            self.last_errors[name] = str(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scada-root", type=Path, default=Path(r"D:\codex\fes"))
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--simulator-url", default="http://127.0.0.1:8710")
    parser.add_argument("--web-port", type=int, default=8878)
    parser.add_argument("--first-iec104-port", type=int, default=2404)
    args = parser.parse_args()
    sys.path.insert(0, str(args.scada_root.resolve()))
    from scdfe_s.web.iec104_service import IEC104Service, IEC104ServiceError
    from scdfe_s.web.server import ApiError, ScadaHTTPServer

    class ModelIEC104Service(IEC104Service):
        def _on_command(self, event, rtu_id=None):
            cause = str(getattr(event.cause, "name", event.cause)).upper()
            if not event.selected and cause.endswith("ACTIVATION") and not cause.endswith("DEACTIVATION"):
                try:
                    bridge.execute(rtu_id, event.kind, event.point_no, event.value)
                except Exception as exc:
                    self._record("ERROR", f"仿真指令执行失败: {exc}", alert=True)
                    return False
            return super()._on_command(event, rtu_id)

        def simulate_command(self, kind, point_no, value):
            with self._lock:
                if self._server is None or kind not in {"yk", "yt"}:
                    raise IEC104ServiceError("请启动模型 IEC104 通道并选择遥控或遥调点")
                try:
                    actual = self._server.prepare_value(kind, int(point_no), value)
                    bridge.execute(self._server.rtu_id, kind, int(point_no), actual)
                except Exception as exc:
                    raise IEC104ServiceError(str(exc)) from exc
                return {**super().simulate_command(kind, point_no, value), "applied_to_simulator": True}

    class ModelScadaServer(ScadaHTTPServer):
        iec104_service_class = ModelIEC104Service

        def switch_database(self, body):
            raise ApiError(409, "此进程绑定仿真专库，切换路径请使用 --db 重新启动")

        def simulator_command(self, rtu, kind, number, body):
            with self.store.connection() as db:
                bound = db.execute("SELECT 1 FROM simulator104_models WHERE rtu_id=?", (rtu,)).fetchone()
            if bound is None:
                return None
            if kind not in {"yk", "yt"} or "value" not in body:
                raise IEC104ServiceError("请选择遥控或遥调点并填写值")
            channel = self.channel_services(rtu_id=rtu)[f"iec104-rtu-{rtu}"]
            return channel.simulate_command(kind, int(number), body["value"])

    logging.basicConfig(level=logging.INFO)
    database = args.db.resolve()
    with ModelScadaServer(("127.0.0.1", args.web_port), db_path=database,
                          workspace_root=database.parent) as server:
        bridge = Bridge(server, args.simulator_url.rstrip("/"), args.first_iec104_port)
        worker = threading.Thread(target=bridge.poll, name="simulator104", daemon=True)
        worker.start()
        LOG.info("scdfe_s Web http://127.0.0.1:%s, SQLite %s", args.web_port, database)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            bridge.stop.set()
            worker.join()


if __name__ == "__main__":
    main()
