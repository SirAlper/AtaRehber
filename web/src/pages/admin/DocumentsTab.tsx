import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, FolderOpen, Lock, Pencil, Trash2, UploadCloud, Users } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { DocumentInfo } from "@/api/types";
import { useToast } from "@/components/Toast";
import { Badge, Button, Card, CardTitle, EmptyState, Field, Input, Modal, Spinner } from "@/components/ui";
import { cn, documentName, splitGroups } from "@/lib/utils";

const ACCEPTED = ".pdf,.docx,.txt";
// How often the list is reloaded while a document is being indexed (a long one takes minutes)
const INDEXING_REFRESH_MS = 3000;

export function DocumentsTab() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [groups, setGroups] = useState("");
  const [dragging, setDragging] = useState(false);
  const [editing, setEditing] = useState<DocumentInfo | null>(null);
  const [editGroups, setEditGroups] = useState("");

  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<{ documents: DocumentInfo[] }>("/api/v1/documents"),
    refetchInterval: (query) => (query.state.data?.documents.some((doc) => doc.indexing) ? INDEXING_REFRESH_MS : false),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["documents"] });
  const fail = (e: unknown) => toast(t("common.error", { error: (e as Error).message }), "error");

  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("file", file!);
      form.append("groups", groups);
      // The file is listed as "indexing" as soon as the server has saved it
      window.setTimeout(refresh, 1000);
      return api("/api/v1/upload-file", { form });
    },
    onSuccess: () => {
      toast(t("documents.uploaded", { name: file?.name }));
      setFile(null);
      // Choosing the same file again must fire onChange
      if (fileRef.current) fileRef.current.value = "";
      setGroups("");
      refresh();
    },
    onError: fail,
  });

  const remove = useMutation({
    mutationFn: (name: string) => api(`/api/v1/documents/${encodeURIComponent(name)}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: fail,
  });

  const access = useMutation({
    mutationFn: ({ name, list }: { name: string; list: string[] }) =>
      api(`/api/v1/documents/${encodeURIComponent(name)}/access`, { method: "PUT", json: { groups: list } }),
    onSuccess: () => {
      setEditing(null);
      toast(t("users.saved"));
      refresh();
    },
    onError: fail,
  });

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) setFile(dropped);
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <Card className="h-fit">
        <CardTitle icon={<UploadCloud className="h-4 w-4" />}>{t("documents.upload")}</CardTitle>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileRef.current?.click()}
          role="button"
          tabIndex={0}
          className={cn(
            "flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 border-dashed px-4 py-8 text-center text-sm transition",
            dragging
              ? "border-fuchsia-400 bg-fuchsia-50/70 dark:bg-fuchsia-500/10"
              : "border-violet-200 hover:border-violet-400 hover:bg-violet-50/60 dark:border-white/15 dark:hover:bg-white/5",
          )}
        >
          <FolderOpen className="h-8 w-8 text-violet-500" />
          {file ? <span className="font-medium">{file.name}</span> : <span className="text-slate-500">{t("documents.drop")}</span>}
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPTED}
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        <div className="mt-4 space-y-3">
          <Field label={t("documents.groups")} hint={t("documents.groupsHint")} htmlFor="groups">
            <Input id="groups" value={groups} onChange={(e) => setGroups(e.target.value)} placeholder="akademik, ogrenci" />
          </Field>
          <Button className="w-full" disabled={!file} loading={upload.isPending} onClick={() => upload.mutate()}>
            {upload.isPending ? t("documents.uploading") : t("documents.upload")}
          </Button>
        </div>
      </Card>

      <Card>
        <CardTitle icon={<FileText className="h-4 w-4" />}>{t("admin.documents")}</CardTitle>
        {documents.isLoading && <Spinner />}
        {documents.data?.documents.length === 0 && <EmptyState icon={<FileText className="h-8 w-8" />}>{t("documents.empty")}</EmptyState>}
        <ul className="space-y-2">
          {documents.data?.documents.map((doc) => (
            <li
              key={doc.filename}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-violet-100 bg-white/60 px-4 py-3 dark:border-white/10 dark:bg-white/[0.03]"
            >
              <FileText className="h-5 w-5 shrink-0 text-violet-500" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium" title={doc.filename}>
                  {documentName(doc.filename)}
                </p>
                <p className="text-xs text-slate-500">
                  {doc.size_kb} KB · {t("documents.chunks", { count: doc.chunk_count })} · {doc.modified_at}
                </p>
              </div>
              {doc.indexing ? (
                <Badge tone="amber">
                  <Spinner className="h-3 w-3" />
                  {t("documents.indexing")}
                </Badge>
              ) : (
                doc.chunk_count === 0 && <Badge tone="rose">{t("documents.notIndexed")}</Badge>
              )}
              {doc.groups.length ? (
                <Badge tone="amber">
                  <Lock className="h-3 w-3" />
                  {doc.groups.join(", ")}
                </Badge>
              ) : (
                <Badge tone="green">
                  <Users className="h-3 w-3" />
                  {t("documents.public")}
                </Badge>
              )}
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("documents.editAccess")}
                title={t("documents.editAccess")}
                onClick={() => {
                  setEditing(doc);
                  setEditGroups(doc.groups.join(", "));
                }}
              >
                <Pencil className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="text-rose-600"
                aria-label={t("documents.delete")}
                title={t("documents.delete")}
                onClick={() => window.confirm(t("documents.confirmDelete", { name: doc.filename })) && remove.mutate(doc.filename)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      </Card>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("documents.editAccess")}>
        {editing && (
          <div className="space-y-4">
            <p className="text-sm font-medium">{editing.filename}</p>
            <Field label={t("documents.groups")} hint={t("documents.groupsHint")} htmlFor="edit-groups">
              <Input id="edit-groups" value={editGroups} onChange={(e) => setEditGroups(e.target.value)} />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setEditing(null)}>
                {t("common.cancel")}
              </Button>
              <Button loading={access.isPending} onClick={() => access.mutate({ name: editing.filename, list: splitGroups(editGroups) })}>
                {t("common.save")}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
