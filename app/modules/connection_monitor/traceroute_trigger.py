import logging
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("docsis.traceroute")


class TracerouteTrigger:
    COOLDOWN_S = 300

    def __init__(self, probe, storage):
        self._probe = probe
        self._storage = storage
        self._last_trace: dict[int, float] = {}
        self._executor = ThreadPoolExecutor(max_workers=1)

    def on_event(self, event: dict) -> None:
        event_type = event.get("event_type")
        if event_type not in ("cm_target_unreachable", "cm_packet_loss_warning"):
            return
        target_id = event.get("details", {}).get("target_id")
        if target_id is None:
            return
        if not self._cooldown_ok(target_id):
            return
        target = self._storage.get_target(target_id)
        if not target:
            return
        reason = "outage" if event_type == "cm_target_unreachable" else "packet_loss"
        self._executor.submit(self._run_and_save, target_id, target["host"], reason)

    def _cooldown_ok(self, target_id: int) -> bool:
        last = self._last_trace.get(target_id, 0)
        return (time.time() - last) >= self.COOLDOWN_S

    def _run_and_save(self, target_id: int, host: str, reason: str) -> None:
        try:
            self._last_trace[target_id] = time.time()
            result = self._probe.run(host)
            if not result.hops:
                return
            self._storage.save_trace(
                target_id=target_id,
                timestamp=time.time(),
                trigger_reason=reason,
                hops=[{
                    "hop_index": h.hop_index,
                    "hop_ip": h.hop_ip,
                    "hop_host": h.hop_host,
                    "latency_ms": h.latency_ms,
                    "probes_responded": h.probes_responded,
                } for h in result.hops],
                route_fingerprint=result.route_fingerprint,
                reached_target=result.reached_target,
            )
        except Exception as e:
            log.error("Traceroute save failed for target %d: %s", target_id, e)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
