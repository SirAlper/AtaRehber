import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { AgentTool, CustomAgent } from "@/api/types";
import { useToast } from "@/components/Toast";
import { Badge, Button, Card, CardTitle, EmptyState, Field, Input, Modal, Spinner, Textarea } from "@/components/ui";
import { cn } from "@/lib/utils";

const EMPTY: CustomAgent = { name: "", display_name: "", description: "", instructions: "", tools: [], enabled: true };

function AgentForm({ initial, tools, onDone }: { initial: CustomAgent; tools: AgentTool[]; onDone: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const isNew = !initial.name;
  const [agent, setAgent] = useState<CustomAgent>(initial);
  const set = <K extends keyof CustomAgent>(key: K, value: CustomAgent[K]) => setAgent((a) => ({ ...a, [key]: value }));

  const save = useMutation({
    mutationFn: () => {
      const { name, display_name, description, instructions, tools: chosen, enabled } = agent;
      const body = { name: name.trim(), display_name, description, instructions, tools: chosen, enabled };
      return api(`/api/v1/admin/custom-agents/${encodeURIComponent(body.name)}`, { method: "PUT", json: body });
    },
    onSuccess: () => {
      toast(t("users.saved"));
      void queryClient.invalidateQueries({ queryKey: ["custom-agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      onDone();
    },
    onError: (e) => toast(t("common.error", { error: (e as Error).message }), "error"),
  });

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {isNew && (
        <Field label={t("customAgents.name")} hint={t("customAgents.nameHint")} htmlFor="agent-name">
          <Input id="agent-name" value={agent.name} onChange={(e) => set("name", e.target.value)} pattern="[a-z][a-z0-9_]{2,39}" required />
        </Field>
      )}
      <Field label={t("customAgents.displayName")} htmlFor="agent-display">
        <Input id="agent-display" value={agent.display_name} onChange={(e) => set("display_name", e.target.value)} required maxLength={60} />
      </Field>
      <Field label={t("customAgents.description")} hint={t("customAgents.descriptionHint")} htmlFor="agent-description">
        <Textarea
          id="agent-description"
          value={agent.description}
          onChange={(e) => set("description", e.target.value)}
          required
          minLength={10}
          maxLength={500}
          className="min-h-20"
        />
      </Field>
      <Field label={t("customAgents.instructions")} hint={t("customAgents.instructionsHint")} htmlFor="agent-instructions">
        <Textarea
          id="agent-instructions"
          value={agent.instructions}
          onChange={(e) => set("instructions", e.target.value)}
          required
          minLength={10}
          maxLength={4000}
          className="min-h-36"
        />
      </Field>
      <fieldset>
        <legend className="mb-2 text-sm font-medium">{t("customAgents.tools")}</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {tools.map((tool) => {
            const checked = agent.tools.includes(tool.name);
            return (
              <label
                key={tool.name}
                className={cn(
                  "flex cursor-pointer gap-3 rounded-xl border p-3 text-sm transition",
                  checked
                    ? "border-violet-400 bg-violet-50 dark:border-violet-400/50 dark:bg-violet-500/10"
                    : "border-violet-100 hover:border-violet-300 dark:border-white/10",
                )}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 accent-violet-600"
                  checked={checked}
                  onChange={(e) =>
                    set("tools", e.target.checked ? [...agent.tools, tool.name] : agent.tools.filter((n) => n !== tool.name))
                  }
                />
                <span>
                  <span className="font-medium">{tool.label}</span>
                  {!tool.available && <span className="ml-1 text-xs text-amber-600">({t("customAgents.unavailable")})</span>}
                  <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">{tool.description}</span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" className="accent-violet-600" checked={agent.enabled} onChange={(e) => set("enabled", e.target.checked)} />
        {t("customAgents.enabled")}
      </label>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onDone}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" loading={save.isPending}>
          {t("customAgents.save")}
        </Button>
      </div>
    </form>
  );
}

export function AgentsTab() {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<CustomAgent | null>(null);

  const agents = useQuery({
    queryKey: ["custom-agents"],
    queryFn: () => api<{ agents: CustomAgent[] }>("/api/v1/admin/custom-agents"),
  });
  const tools = useQuery({
    queryKey: ["agent-tools", i18n.language],
    queryFn: () => api<{ tools: AgentTool[] }>("/api/v1/admin/agent-tools", { query: { language: i18n.language } }),
  });
  const remove = useMutation({
    mutationFn: (name: string) => api(`/api/v1/admin/custom-agents/${encodeURIComponent(name)}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["custom-agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: (e) => toast(t("common.error", { error: (e as Error).message }), "error"),
  });
  const labels = Object.fromEntries((tools.data?.tools ?? []).map((tool) => [tool.name, tool.label]));

  return (
    <Card>
      <CardTitle
        icon={<Bot className="h-4 w-4" />}
        action={
          <Button size="sm" onClick={() => setEditing(EMPTY)}>
            <Plus className="h-4 w-4" />
            {t("customAgents.new")}
          </Button>
        }
      >
        {t("admin.agents")}
      </CardTitle>
      <p className="-mt-2 mb-4 text-sm text-slate-600 dark:text-slate-300">{t("customAgents.subtitle")}</p>
      {agents.isLoading && <Spinner />}
      {agents.data?.agents.length === 0 && <EmptyState icon={<Bot className="h-8 w-8" />}>{t("customAgents.empty")}</EmptyState>}
      <div className="grid gap-3 md:grid-cols-2">
        {agents.data?.agents.map((agent) => (
          <article
            key={agent.name}
            className="animate-fade-up rounded-2xl border border-violet-100 bg-gradient-to-br from-white/80 to-violet-50/60 p-4 dark:border-white/10 dark:from-white/[0.04] dark:to-violet-500/[0.06]"
          >
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-fuchsia-600 text-white shadow-md">
                <Bot className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-semibold">{agent.display_name}</h3>
                  <Badge tone={agent.available ? "green" : "slate"}>
                    {agent.available ? t("customAgents.active") : t("customAgents.inactive")}
                  </Badge>
                </div>
                <p className="font-mono text-xs text-slate-400">{agent.name}</p>
              </div>
            </div>
            <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{agent.description}</p>
            <div className="mt-3 flex flex-wrap gap-1">
              {agent.tools.map((tool) => (
                <Badge key={tool} tone="violet">
                  {labels[tool] ?? tool}
                </Badge>
              ))}
            </div>
            <div className="mt-3 flex justify-end gap-1">
              <Button variant="ghost" size="sm" onClick={() => setEditing(agent)}>
                <Pencil className="h-3.5 w-3.5" />
                {t("customAgents.edit")}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-rose-600"
                onClick={() => window.confirm(t("customAgents.confirmDelete", { name: agent.display_name })) && remove.mutate(agent.name)}
              >
                <Trash2 className="h-3.5 w-3.5" />
                {t("customAgents.delete")}
              </Button>
            </div>
          </article>
        ))}
      </div>
      <Modal
        open={!!editing}
        onClose={() => setEditing(null)}
        title={editing?.name ? t("customAgents.edit") : t("customAgents.new")}
        wide
      >
        {editing && <AgentForm initial={editing} tools={tools.data?.tools ?? []} onDone={() => setEditing(null)} />}
      </Modal>
    </Card>
  );
}
