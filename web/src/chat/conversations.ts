import { useCallback, useEffect, useState } from "react";

import type { QueryResult } from "@/api/types";
import { newId } from "@/lib/utils";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Stages shown while the answer is prepared ("Searching the documents…") */
  stages?: string[];
  pending?: boolean;
  result?: QueryResult;
  error?: string;
  feedback?: "positive" | "negative";
}

export interface Conversation {
  /** Also the API's session_id, so follow-up questions are understood */
  id: string;
  title: string;
  updatedAt: number;
  messages: ChatMessage[];
}

const MAX_CONVERSATIONS = 30;

function storageKey(username: string) {
  return `olr.chats.${username}`;
}

function load(username: string | null): Conversation[] {
  if (!username) return [];
  try {
    const raw = localStorage.getItem(storageKey(username));
    const list = raw ? (JSON.parse(raw) as Conversation[]) : [];
    // Answers still pending when the page was closed never arrive
    return list.map((c) => ({ ...c, messages: c.messages.filter((m) => !m.pending) }));
  } catch {
    return [];
  }
}

export function newConversation(): Conversation {
  return { id: newId(), title: "", updatedAt: Date.now(), messages: [] };
}

/**
 * The user's conversations, kept in this browser. Guests (username null) keep them in memory only, so the next
 * visitor on a shared computer does not see them.
 */
export function useConversations(username: string | null) {
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const stored = load(username);
    return stored.length ? stored : [newConversation()];
  });
  const [activeId, setActiveId] = useState<string>(() => conversations[0].id);

  useEffect(() => {
    if (!username) return;
    try {
      const kept = conversations.filter((c) => c.messages.length).slice(0, MAX_CONVERSATIONS);
      localStorage.setItem(storageKey(username), JSON.stringify(kept));
    } catch {
      // Storage full or blocked: the conversations stay for this page view
    }
  }, [conversations, username]);

  const active = conversations.find((c) => c.id === activeId) ?? conversations[0];

  // State updates are decided here, not inside setConversations updaters, which React may run twice
  const create = useCallback(() => {
    const empty = conversations.find((c) => !c.messages.length);
    if (empty) {
      setActiveId(empty.id);
      return;
    }
    const fresh = newConversation();
    setConversations((list) => [fresh, ...list]);
    setActiveId(fresh.id);
  }, [conversations]);

  const update = useCallback((id: string, change: (conversation: Conversation) => Conversation) => {
    setConversations((list) =>
      list
        .map((c) => (c.id === id ? { ...change(c), updatedAt: Date.now() } : c))
        .sort((a, b) => b.updatedAt - a.updatedAt),
    );
  }, []);

  const remove = useCallback(
    (id: string) => {
      const rest = conversations.filter((c) => c.id !== id);
      const next = rest.length ? rest : [newConversation()];
      setConversations(next);
      if (id === activeId) setActiveId(next[0].id);
    },
    [conversations, activeId],
  );

  // One question at a time across all conversations: the stop button belongs to the running one
  const busy = conversations.some((c) => c.messages.some((m) => m.pending));

  return { conversations, active, busy, select: setActiveId, create, update, remove };
}
