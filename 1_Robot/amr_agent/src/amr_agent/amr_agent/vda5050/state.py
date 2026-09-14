"""VDA 5050 state / connection message builders (pure Python)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional, Tuple

from .models import footprint_polygon, swing_polygon
from .order import OrderBook
from .topics import PROTOCOL_VERSION


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_error(error_type: str, description: str, level: str = "WARNING",
               references: Iterable[Tuple[str, str]] = ()) -> dict:
    return {"errorType": error_type, "errorLevel": level, "errorDescription": description,
            "errorReferences": [{"referenceKey": k, "referenceValue": v} for k, v in references]}


class StateBuilder:
    def __init__(self, manufacturer: str, serial: str, map_id: str = "") -> None:
        self.manufacturer = manufacturer
        self.serial = serial
        self.map_id = map_id
        self._header = 0

    def _header_block(self) -> dict:
        self._header += 1
        return {"headerId": self._header, "timestamp": now_iso(), "version": PROTOCOL_VERSION,
                "manufacturer": self.manufacturer, "serialNumber": self.serial}

    def state(self, book: OrderBook, pose: Optional[Tuple[float, float, float]],
              velocity: Tuple[float, float, float] = (0.0, 0.0, 0.0), driving: bool = False,
              paused: bool = False, errors: Iterable[dict] = (), information: Iterable[dict] = (),
              battery_charge: float = 100.0, operating_mode: str = "AUTOMATIC",
              localization_score: Optional[float] = None, new_base_request: bool = False,
              distance_since_last_node: float = 0.0, action_states: Iterable[dict] = (),
              battery: Optional[dict] = None) -> dict:
        """battery: BatteryModel.state() — 없으면 battery_charge 로 채운 고정값."""
        last = book.last_node
        pos = None
        if pose is not None:
            pos = {"x": pose[0], "y": pose[1], "theta": pose[2], "mapId": self.map_id,
                   "positionInitialized": True}
            if localization_score is not None:
                pos["localizationScore"] = localization_score
        msg = {**self._header_block(),
               "orderId": book.order_id, "orderUpdateId": book.order_update_id, "zoneSetId": "",
               "lastNodeId": last.node_id if last else "",
               "lastNodeSequenceId": last.sequence_id if last else 0,
               "nodeStates": book.node_states(), "edgeStates": book.edge_states(),
               "driving": driving, "paused": paused, "newBaseRequest": new_base_request,
               "distanceSinceLastNode": distance_since_last_node,
               "actionStates": list(action_states),
               "batteryState": dict(battery) if battery else {"batteryCharge": battery_charge, "charging": False},
               "operatingMode": operating_mode,
               "errors": list(errors), "information": list(information),
               "safetyState": {"eStop": "NONE", "fieldViolation": False},
               "velocity": {"vx": velocity[0], "vy": velocity[1], "omega": velocity[2]},
               "loads": []}
        if pos is not None:
            msg["agvPosition"] = pos
        return msg

    def factsheet(self, p: dict) -> dict:
        """VDA 5050 2.0.0 factsheet ← 기종 프로파일 dict (models.load_model_profile). retained QoS1, ONLINE 직후."""
        wheels = [{"type": w["type"], "isActiveDriven": bool(w["is_active_driven"]),
                   "isActiveSteered": bool(w["is_active_steered"]),
                   "position": {"x": float(w["position"]["x"]), "y": float(w["position"]["y"])},
                   "diameter": float(w["diameter"]), "width": float(w["width"])} for w in p["wheels"]]
        return {**self._header_block(),
                "typeSpecification": {"seriesName": p["model"], "seriesDescription": p.get("description", ""),
                                      "agvKinematic": p["kinematic"], "agvClass": p["agv_class"],
                                      "maxLoadMass": float(p["max_load_kg"]),
                                      "localizationTypes": ["NATURAL"], "navigationTypes": ["AUTONOMOUS"]},
                "physicalParameters": {"speedMin": float(p["v_min"]), "speedMax": float(p["v_max"]),
                                       "accelerationMax": float(p["a_max"]),
                                       "decelerationMax": float(p.get("d_max", p["a_max"])),
                                       "heightMin": float(p["height"]), "heightMax": float(p["height"]),
                                       "width": float(p["width"]), "length": float(p["length"])},
                "protocolLimits": {"maxStringLens": {}, "maxArrayLens": {},
                                   "timing": {"minOrderInterval": float(p["order_interval"]),
                                              "minStateInterval": float(p["state_interval"]),
                                              "defaultStateInterval": float(p["state_interval"])}},
                "protocolFeatures": {"optionalParameters": [], "agvActions": [
                    {"actionType": "cancelOrder", "actionScopes": ["INSTANT"], "actionParameters": [],
                     "resultDescription": "drop all unreached nodes; lastNode stays"}]},
                "agvGeometry": {"wheelDefinitions": wheels,
                                "envelopes2d": [{"set": "footprint", "polygonPoints": footprint_polygon(p),
                                                 "description": "chassis outline, vehicle frame (x forward)"},
                                                {"set": "swing", "polygonPoints": swing_polygon(p),
                                                 "description": "spot-turn swing circle"}]},
                "loadSpecification": {"loadPositions": [], "loadSets": []}}

    def connection(self, connection_state: str) -> dict:
        assert connection_state in ("ONLINE", "OFFLINE", "CONNECTIONBROKEN")
        return {**self._header_block(), "connectionState": connection_state}
