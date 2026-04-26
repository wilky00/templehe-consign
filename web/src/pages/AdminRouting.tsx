// ABOUTME: Phase 4 Sprint 4 — admin lead routing console with drag-to-reorder + per-rule test.
// ABOUTME: Tabs per rule_type; @dnd-kit-driven sortable list; per-row Edit/Test/Delete.
import { useMemo, useState } from "react";
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { RoutingRuleForm } from "../components/admin/RoutingRuleForm";
import { RoutingRuleTester } from "../components/admin/RoutingRuleTester";
import {
  listRoutingRules,
  reorderRoutingRules,
  softDeleteRoutingRule,
} from "../api/admin";
import { ApiError } from "../api/client";
import type { RoutingRule, RoutingRuleType, UUID } from "../api/types";

const RULE_TYPE_TABS: { value: RoutingRuleType; label: string; help: string }[] = [
  {
    value: "ad_hoc",
    label: "Ad hoc",
    help: "Match a specific customer ID or every customer from one email domain.",
  },
  {
    value: "geographic",
    label: "Geographic",
    help: "Match by US state, ZIP code, or a metro radius (lat/lng + miles).",
  },
  {
    value: "round_robin",
    label: "Round robin",
    help: "Distribute to a rotating pool of reps. The fallback when no other rule fires.",
  },
];

export function AdminRoutingPage() {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<RoutingRuleType>("ad_hoc");
  const [editTarget, setEditTarget] = useState<RoutingRule | null>(null);
  const [createOpen, setCreateOpen] = useState<boolean>(false);
  const [testTarget, setTestTarget] = useState<RoutingRule | null>(null);

  const query = useQuery({
    queryKey: ["admin-routing-rules"],
    queryFn: () => listRoutingRules(false),
  });

  const rulesForTab = useMemo<RoutingRule[]>(() => {
    if (!query.data) return [];
    return query.data.rules
      .filter((r) => r.rule_type === activeTab)
      .sort((a, b) => a.priority - b.priority);
  }, [query.data, activeTab]);

  const reorderMutation = useMutation({
    mutationFn: (ordered_ids: UUID[]) =>
      reorderRoutingRules({ rule_type: activeTab, ordered_ids }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-routing-rules"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (ruleId: UUID) => softDeleteRoutingRule(ruleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-routing-rules"] }),
  });

  const sensors = useSensors(useSensor(PointerSensor));

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const ids = rulesForTab.map((r) => r.id);
    const oldIndex = ids.indexOf(active.id as UUID);
    const newIndex = ids.indexOf(over.id as UUID);
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(ids, oldIndex, newIndex);
    reorderMutation.mutate(next);
  };

  const tabMeta = RULE_TYPE_TABS.find((t) => t.value === activeTab)!;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Lead routing</h1>
          <p className="mt-1 text-sm text-gray-600">
            Rules are evaluated by type bucket: ad-hoc → geographic →
            round-robin. Drag a row to reorder priorities atomically.
          </p>
        </div>
        <Button variant="primary" onClick={() => setCreateOpen(true)}>
          Add {tabMeta.label.toLowerCase()} rule
        </Button>
      </div>

      <div role="tablist" className="flex flex-wrap gap-2 border-b border-gray-200">
        {RULE_TYPE_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.value}
            onClick={() => setActiveTab(tab.value)}
            className={
              activeTab === tab.value
                ? "border-b-2 border-gray-900 px-3 py-2 text-sm font-medium text-gray-900"
                : "border-b-2 border-transparent px-3 py-2 text-sm font-medium text-gray-600 hover:text-gray-900"
            }
          >
            {tab.label}
          </button>
        ))}
      </div>

      <p className="text-sm text-gray-600">{tabMeta.help}</p>

      {query.isLoading && <Spinner />}
      {query.isError && (
        <Alert tone="error" title="Could not load rules">
          {(query.error as Error).message}
        </Alert>
      )}
      {reorderMutation.error && (
        <Alert tone="error" title="Reorder failed">
          {reorderMutation.error instanceof ApiError
            ? reorderMutation.error.detail
            : (reorderMutation.error as Error).message}
        </Alert>
      )}

      {query.data && (
        <Card>
          {rulesForTab.length === 0 ? (
            <p className="text-sm text-gray-500">No rules of this type yet.</p>
          ) : (
            <DndContext sensors={sensors} onDragEnd={onDragEnd}>
              <SortableContext
                items={rulesForTab.map((r) => r.id)}
                strategy={verticalListSortingStrategy}
              >
                <ul className="divide-y divide-gray-100">
                  {rulesForTab.map((rule) => (
                    <SortableRow
                      key={rule.id}
                      rule={rule}
                      onEdit={() => setEditTarget(rule)}
                      onTest={() => setTestTarget(rule)}
                      onDelete={() => deleteMutation.mutate(rule.id)}
                      isReordering={reorderMutation.isPending}
                    />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>
          )}
        </Card>
      )}

      {(createOpen || editTarget) && (
        <RoutingRuleForm
          ruleType={activeTab}
          existing={editTarget}
          onClose={() => {
            setCreateOpen(false);
            setEditTarget(null);
          }}
        />
      )}

      {testTarget && (
        <RoutingRuleTester
          rule={testTarget}
          onClose={() => setTestTarget(null)}
        />
      )}
    </div>
  );
}

interface RowProps {
  rule: RoutingRule;
  onEdit: () => void;
  onTest: () => void;
  onDelete: () => void;
  isReordering: boolean;
}

function SortableRow({ rule, onEdit, onTest, onDelete, isReordering }: RowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: rule.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <li
      ref={setNodeRef}
      style={style}
      className="flex items-center justify-between gap-3 py-3 text-sm"
    >
      <button
        type="button"
        aria-label="Drag to reorder"
        {...attributes}
        {...listeners}
        className="cursor-grab rounded p-1 text-gray-400 hover:bg-gray-100"
      >
        ⋮⋮
      </button>
      <div className="min-w-0 flex-1">
        <div className="font-mono text-xs text-gray-500">priority {rule.priority}</div>
        <div className="font-medium text-gray-900">
          {_summarize(rule)}
          {!rule.is_active && (
            <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
              inactive
            </span>
          )}
        </div>
        {rule.assigned_user_id && (
          <div className="text-xs text-gray-500">
            → user {rule.assigned_user_id.slice(0, 8)}…
          </div>
        )}
      </div>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" onClick={onTest} disabled={isReordering}>
          Test
        </Button>
        <Button size="sm" variant="secondary" onClick={onEdit} disabled={isReordering}>
          Edit
        </Button>
        <Button size="sm" variant="danger" onClick={onDelete} disabled={isReordering}>
          Delete
        </Button>
      </div>
    </li>
  );
}

function _summarize(rule: RoutingRule): string {
  const c = (rule.conditions ?? {}) as Record<string, unknown>;
  if (rule.rule_type === "ad_hoc") {
    return `${c.condition_type ?? "?"} = ${c.value ?? "?"}`;
  }
  if (rule.rule_type === "geographic") {
    const parts: string[] = [];
    if (Array.isArray(c.state_list) && c.state_list.length) {
      parts.push(`states: ${(c.state_list as string[]).join(", ")}`);
    }
    if (Array.isArray(c.zip_list) && c.zip_list.length) {
      parts.push(`zips: ${(c.zip_list as string[]).slice(0, 3).join(", ")}${
        (c.zip_list as string[]).length > 3 ? "…" : ""
      }`);
    }
    if (c.metro_area && typeof c.metro_area === "object") {
      const m = c.metro_area as Record<string, unknown>;
      parts.push(`metro: ${m.name ?? "(unnamed)"} ±${m.radius_miles}mi`);
    }
    return parts.join(" · ") || "(no conditions)";
  }
  const ids = (c.rep_ids as string[]) ?? [];
  return `${ids.length} rep${ids.length === 1 ? "" : "s"} · idx ${rule.round_robin_index}`;
}
