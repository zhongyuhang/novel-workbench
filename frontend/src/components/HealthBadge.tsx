import type { BackendHealthState } from "../features/library/useBackendHealth.ts";

type HealthBadgeProps = {
  state: BackendHealthState;
};

export function HealthBadge({ state }: HealthBadgeProps) {
  if (state.kind === "loading") {
    return (
      <p className="health health-loading" role="status" aria-live="polite">
        正在检查后端
      </p>
    );
  }

  if (state.kind === "ready") {
    return (
      <p className="health health-ok" role="status" aria-live="polite">
        后端可用
        <span className="health-detail">
          {state.report.service} {state.report.version}
        </span>
      </p>
    );
  }

  return (
    <p className="health health-down" role="status" aria-live="polite">
      后端不可用
      <span className="health-detail">{state.message}</span>
    </p>
  );
}
