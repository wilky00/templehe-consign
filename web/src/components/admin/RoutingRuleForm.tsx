// ABOUTME: Phase 4 Sprint 4 — create/edit form for one routing rule.
// ABOUTME: Form switches conditions widget per rule_type (ad_hoc / geographic / round_robin).
import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { createRoutingRule, updateRoutingRule } from "../../api/admin";
import { ApiError } from "../../api/client";
import type { RoutingRule, RoutingRuleType, UUID } from "../../api/types";

interface Props {
  ruleType: RoutingRuleType;
  existing: RoutingRule | null;
  onClose: () => void;
}

type ConditionsState =
  | {
      kind: "ad_hoc";
      condition_type: "customer_id" | "email_domain";
      value: string;
    }
  | {
      kind: "geographic";
      states_csv: string;
      zips_csv: string;
      metro_name: string;
      metro_lat: string;
      metro_lon: string;
      metro_radius: string;
    }
  | {
      kind: "round_robin";
      rep_ids_csv: string;
    };

function _initialState(rule: RoutingRule | null, ruleType: RoutingRuleType): ConditionsState {
  const cond = (rule?.conditions ?? {}) as Record<string, unknown>;
  if (ruleType === "ad_hoc") {
    return {
      kind: "ad_hoc",
      condition_type:
        (cond.condition_type as "customer_id" | "email_domain") ?? "email_domain",
      value: (cond.value as string) ?? "",
    };
  }
  if (ruleType === "geographic") {
    const metro = cond.metro_area as Record<string, unknown> | undefined;
    return {
      kind: "geographic",
      states_csv: ((cond.state_list as string[]) ?? []).join(", "),
      zips_csv: ((cond.zip_list as string[]) ?? []).join(", "),
      metro_name: (metro?.name as string) ?? "",
      metro_lat: metro?.center_lat != null ? String(metro.center_lat) : "",
      metro_lon: metro?.center_lon != null ? String(metro.center_lon) : "",
      metro_radius: metro?.radius_miles != null ? String(metro.radius_miles) : "",
    };
  }
  return {
    kind: "round_robin",
    rep_ids_csv: ((cond.rep_ids as string[]) ?? []).join(", "),
  };
}

function _buildConditions(state: ConditionsState): Record<string, unknown> | null {
  if (state.kind === "ad_hoc") {
    return { condition_type: state.condition_type, value: state.value.trim() };
  }
  if (state.kind === "geographic") {
    const out: Record<string, unknown> = {};
    const states = state.states_csv
      .split(",")
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    if (states.length) out.state_list = states;
    const zips = state.zips_csv
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (zips.length) out.zip_list = zips;
    if (state.metro_lat && state.metro_lon && state.metro_radius) {
      out.metro_area = {
        name: state.metro_name || null,
        center_lat: Number(state.metro_lat),
        center_lon: Number(state.metro_lon),
        radius_miles: Number(state.metro_radius),
      };
    }
    return out;
  }
  return {
    rep_ids: state.rep_ids_csv
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  };
}

export function RoutingRuleForm({ ruleType, existing, onClose }: Props) {
  const qc = useQueryClient();
  const [conditions, setConditions] = useState<ConditionsState>(() =>
    _initialState(existing, ruleType),
  );
  const [priority, setPriority] = useState<number>(existing?.priority ?? 100);
  const [assignedUserId, setAssignedUserId] = useState<string>(
    existing?.assigned_user_id ?? "",
  );
  const [isActive, setIsActive] = useState<boolean>(existing?.is_active ?? true);

  useEffect(() => {
    setConditions(_initialState(existing, ruleType));
    setPriority(existing?.priority ?? 100);
    setAssignedUserId(existing?.assigned_user_id ?? "");
    setIsActive(existing?.is_active ?? true);
  }, [existing, ruleType]);

  const mutation = useMutation({
    mutationFn: async () => {
      const payloadConditions = _buildConditions(conditions);
      const trimmedUserId = assignedUserId.trim() || null;
      if (existing) {
        return updateRoutingRule(existing.id, {
          priority,
          conditions: payloadConditions,
          assigned_user_id: trimmedUserId as UUID | null,
          is_active: isActive,
        });
      }
      return createRoutingRule({
        rule_type: ruleType,
        priority,
        conditions: payloadConditions,
        assigned_user_id: trimmedUserId as UUID | null,
        is_active: isActive,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-routing-rules"] });
      onClose();
    },
  });

  const error =
    mutation.error instanceof ApiError
      ? mutation.error.detail
      : mutation.error
        ? (mutation.error as Error).message
        : null;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="rule-form-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-xl rounded-lg bg-white p-6 shadow-xl">
        <h2 id="rule-form-title" className="text-lg font-semibold text-gray-900">
          {existing ? "Edit" : "New"} {ruleType.replace("_", " ")} rule
        </h2>

        <form onSubmit={onSubmit} className="mt-4 space-y-3">
          <label className="block text-sm">
            <span className="block font-medium text-gray-700">Priority</span>
            <input
              type="number"
              required
              min={0}
              max={10_000}
              value={priority}
              onChange={(e) => setPriority(Number(e.target.value))}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            />
            <p className="mt-1 text-xs text-gray-500">
              Lower numbers match first within this rule type. Use the
              drag-reorder controls on the list page to renumber atomically.
            </p>
          </label>

          {ruleType !== "round_robin" && (
            <label className="block text-sm">
              <span className="block font-medium text-gray-700">Assigned user ID</span>
              <input
                type="text"
                value={assignedUserId}
                onChange={(e) => setAssignedUserId(e.target.value)}
                placeholder="UUID of sales / sales_manager / admin"
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
              />
              <p className="mt-1 text-xs text-gray-500">
                Leave blank to make this rule a no-op (matches but doesn't
                assign — useful while configuring).
              </p>
            </label>
          )}

          {conditions.kind === "ad_hoc" && (
            <>
              <label className="block text-sm">
                <span className="block font-medium text-gray-700">Condition type</span>
                <select
                  value={conditions.condition_type}
                  onChange={(e) =>
                    setConditions({
                      ...conditions,
                      condition_type: e.target.value as
                        | "customer_id"
                        | "email_domain",
                    })
                  }
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                >
                  <option value="email_domain">Email domain</option>
                  <option value="customer_id">Customer ID</option>
                </select>
              </label>
              <label className="block text-sm">
                <span className="block font-medium text-gray-700">Value</span>
                <input
                  required
                  value={conditions.value}
                  onChange={(e) =>
                    setConditions({ ...conditions, value: e.target.value })
                  }
                  placeholder={
                    conditions.condition_type === "email_domain"
                      ? "acme.com"
                      : "uuid"
                  }
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                />
              </label>
            </>
          )}

          {conditions.kind === "geographic" && (
            <>
              <label className="block text-sm">
                <span className="block font-medium text-gray-700">
                  States (comma-separated 2-letter)
                </span>
                <input
                  value={conditions.states_csv}
                  onChange={(e) =>
                    setConditions({ ...conditions, states_csv: e.target.value })
                  }
                  placeholder="TX, CO, NM"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                />
              </label>
              <label className="block text-sm">
                <span className="block font-medium text-gray-700">
                  ZIP codes (comma-separated)
                </span>
                <input
                  value={conditions.zips_csv}
                  onChange={(e) =>
                    setConditions({ ...conditions, zips_csv: e.target.value })
                  }
                  placeholder="80210, 80211"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                />
              </label>
              <fieldset className="rounded-md border border-gray-200 p-3">
                <legend className="px-1 text-xs font-medium text-gray-700">
                  Metro radius (optional)
                </legend>
                <div className="grid grid-cols-2 gap-2">
                  <label className="text-xs">
                    Name
                    <input
                      value={conditions.metro_name}
                      onChange={(e) =>
                        setConditions({ ...conditions, metro_name: e.target.value })
                      }
                      className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="text-xs">
                    Radius (miles)
                    <input
                      type="number"
                      value={conditions.metro_radius}
                      onChange={(e) =>
                        setConditions({ ...conditions, metro_radius: e.target.value })
                      }
                      className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="text-xs">
                    Center latitude
                    <input
                      type="number"
                      step="any"
                      value={conditions.metro_lat}
                      onChange={(e) =>
                        setConditions({ ...conditions, metro_lat: e.target.value })
                      }
                      className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="text-xs">
                    Center longitude
                    <input
                      type="number"
                      step="any"
                      value={conditions.metro_lon}
                      onChange={(e) =>
                        setConditions({ ...conditions, metro_lon: e.target.value })
                      }
                      className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1 text-sm"
                    />
                  </label>
                </div>
              </fieldset>
            </>
          )}

          {conditions.kind === "round_robin" && (
            <label className="block text-sm">
              <span className="block font-medium text-gray-700">
                Rep IDs (comma-separated UUIDs, in rotation order)
              </span>
              <textarea
                required
                rows={3}
                value={conditions.rep_ids_csv}
                onChange={(e) =>
                  setConditions({ ...conditions, rep_ids_csv: e.target.value })
                }
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
          )}

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
            />
            <span className="text-gray-700">Active</span>
          </label>

          {error && (
            <Alert tone="error" title="Could not save the rule">
              {error}
            </Alert>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={mutation.isPending}>
              {mutation.isPending ? "Saving…" : existing ? "Save changes" : "Create"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
