// ABOUTME: Lifecycle hook — acquire on mount, heartbeat every 60s, release on unmount.
// ABOUTME: Exposes { status, conflict, overrideAvailable, refresh } so the detail page can render the right banner.
import { useEffect, useRef, useState } from "react";
import { acquireLock, heartbeatLock, releaseLock } from "../api/sales";
import { ApiError } from "../api/client";
import type { LockConflict, LockInfo } from "../api/types";

export type LockState =
  | { status: "idle" }
  | { status: "acquiring" }
  | { status: "held"; info: LockInfo }
  | { status: "expired" }
  | { status: "conflict"; conflict: LockConflict }
  | { status: "error"; detail: string };

const HEARTBEAT_MS = 60_000;

export function useRecordLock(recordId: string | undefined): {
  lock: LockState;
  refresh: () => Promise<void>;
} {
  const [lock, setLock] = useState<LockState>({ status: "idle" });
  const heartbeatRef = useRef<number | null>(null);
  const releasedRef = useRef(false);

  const clearHeartbeat = () => {
    if (heartbeatRef.current !== null) {
      window.clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  };

  const refresh = async () => {
    if (!recordId) return;
    try {
      const info = await heartbeatLock(recordId);
      setLock({ status: "held", info });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setLock({ status: "expired" });
        clearHeartbeat();
      }
    }
  };

  useEffect(() => {
    if (!recordId) return;
    let cancelled = false;

    (async () => {
      setLock({ status: "acquiring" });
      try {
        const info = await acquireLock(recordId);
        if (cancelled) return;
        setLock({ status: "held", info });
        heartbeatRef.current = window.setInterval(refresh, HEARTBEAT_MS);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 409) {
          // Body is the LockConflict shape; we stash it for the UI.
          const conflict: LockConflict = {
            detail: err.detail,
            locked_by: "",
            locked_at: "",
            expires_at: "",
          };
          try {
            const parsed = JSON.parse(err.detail);
            if (parsed && typeof parsed === "object") {
              Object.assign(conflict, parsed);
            }
          } catch {
            // ignore — detail is a plain string
          }
          setLock({ status: "conflict", conflict });
        } else {
          const detail =
            err instanceof Error ? err.message : "lock acquire failed";
          setLock({ status: "error", detail });
        }
      }
    })();

    return () => {
      cancelled = true;
      clearHeartbeat();
      if (recordId && !releasedRef.current) {
        releasedRef.current = true;
        releaseLock(recordId).catch(() => {
          // Best-effort; backend release is idempotent.
        });
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId]);

  return { lock, refresh };
}
