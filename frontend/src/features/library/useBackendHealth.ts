import { useEffect, useState } from "react";
import { getHealth } from "../../api/client.ts";
import { HealthCheckError, type HealthReport } from "../../api/types.ts";

export type BackendHealthState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly report: HealthReport }
  | { readonly kind: "unavailable"; readonly message: string };

export function useBackendHealth(): BackendHealthState {
  const [state, setState] = useState<BackendHealthState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    getHealth(controller.signal)
      .then((report) => {
        if (active) {
          setState({ kind: "ready", report });
        }
      })
      .catch((error: unknown) => {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) {
          return;
        }
        const message =
          error instanceof HealthCheckError ? error.message : "健康检查失败。";
        setState({ kind: "unavailable", message });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  return state;
}
