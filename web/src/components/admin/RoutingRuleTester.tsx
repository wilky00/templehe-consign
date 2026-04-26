// ABOUTME: Phase 4 Sprint 4 — feed synthetic input into one rule, see if it matches.
// ABOUTME: Read-only — no round-robin index increment, no audit log, no assignment.
import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { testRoutingRule } from "../../api/admin";
import { ApiError } from "../../api/client";
import type { RoutingRule, RoutingRuleTestRequest } from "../../api/types";

interface Props {
  rule: RoutingRule;
  onClose: () => void;
}

export function RoutingRuleTester({ rule, onClose }: Props) {
  const [input, setInput] = useState<RoutingRuleTestRequest>({});

  const mutation = useMutation({
    mutationFn: () => testRoutingRule(rule.id, input),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  const error =
    mutation.error instanceof ApiError
      ? mutation.error.detail
      : mutation.error
        ? (mutation.error as Error).message
        : null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="rule-tester-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        <h2 id="rule-tester-title" className="text-lg font-semibold text-gray-900">
          Test routing rule
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          {rule.rule_type.replace("_", " ")} · priority {rule.priority}
        </p>

        <form onSubmit={onSubmit} className="mt-4 space-y-3">
          {rule.rule_type === "ad_hoc" && (
            <>
              <label className="block text-sm">
                <span className="block font-medium text-gray-700">Customer email</span>
                <input
                  type="email"
                  value={input.customer_email ?? ""}
                  onChange={(e) =>
                    setInput({ ...input, customer_email: e.target.value || null })
                  }
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                />
              </label>
              <label className="block text-sm">
                <span className="block font-medium text-gray-700">Customer ID</span>
                <input
                  value={input.customer_id ?? ""}
                  onChange={(e) =>
                    setInput({ ...input, customer_id: e.target.value || null })
                  }
                  placeholder="UUID"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                />
              </label>
            </>
          )}

          {rule.rule_type === "geographic" && (
            <>
              <label className="block text-sm">
                <span className="block font-medium text-gray-700">State (2-letter)</span>
                <input
                  value={input.customer_state ?? ""}
                  onChange={(e) =>
                    setInput({
                      ...input,
                      customer_state: e.target.value.toUpperCase() || null,
                    })
                  }
                  maxLength={2}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                />
              </label>
              <label className="block text-sm">
                <span className="block font-medium text-gray-700">ZIP</span>
                <input
                  value={input.customer_zip ?? ""}
                  onChange={(e) =>
                    setInput({ ...input, customer_zip: e.target.value || null })
                  }
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="block text-sm">
                  <span className="block font-medium text-gray-700">Latitude</span>
                  <input
                    type="number"
                    step="any"
                    value={input.customer_lat ?? ""}
                    onChange={(e) =>
                      setInput({
                        ...input,
                        customer_lat: e.target.value === "" ? null : Number(e.target.value),
                      })
                    }
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                  />
                </label>
                <label className="block text-sm">
                  <span className="block font-medium text-gray-700">Longitude</span>
                  <input
                    type="number"
                    step="any"
                    value={input.customer_lng ?? ""}
                    onChange={(e) =>
                      setInput({
                        ...input,
                        customer_lng: e.target.value === "" ? null : Number(e.target.value),
                      })
                    }
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                  />
                </label>
              </div>
            </>
          )}

          {rule.rule_type === "round_robin" && (
            <p className="text-sm text-gray-600">
              Round-robin matches every customer; the test reports the rep
              that <em>would</em> be picked next without claiming.
            </p>
          )}

          {error && (
            <Alert tone="error" title="Test request failed">
              {error}
            </Alert>
          )}

          {mutation.data && (
            <Alert tone={mutation.data.matched ? "success" : "warning"} title={
              mutation.data.matched ? "Matched" : "No match"
            }>
              <p>{mutation.data.reason}</p>
              {mutation.data.would_assign_to && (
                <p className="mt-1">
                  Would assign to user{" "}
                  <code className="rounded bg-white px-1 text-xs">
                    {mutation.data.would_assign_to}
                  </code>
                </p>
              )}
            </Alert>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Close
            </Button>
            <Button type="submit" variant="primary" disabled={mutation.isPending}>
              {mutation.isPending ? "Testing…" : "Run test"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
