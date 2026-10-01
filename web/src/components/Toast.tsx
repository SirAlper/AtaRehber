import { CheckCircle2, AlertTriangle } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

interface Toast {
  id: number;
  text: string;
  tone: "success" | "error";
}

const ToastContext = createContext<(text: string, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const show = useCallback((text: string, tone: Toast["tone"] = "success") => {
    const id = Date.now() + Math.random();
    setToasts((list) => [...list, { id, text, tone }]);
    setTimeout(() => setToasts((list) => list.filter((toast) => toast.id !== id)), 4000);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="pointer-events-none fixed top-3 right-3 left-3 z-50 flex flex-col gap-2 sm:top-auto sm:bottom-4 sm:left-auto sm:max-w-sm" role="status">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "glass animate-fade-up flex items-start gap-2 px-4 py-3 text-sm",
              toast.tone === "error" && "border-rose-200 dark:border-rose-400/20",
            )}
          >
            {toast.tone === "success" ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
            ) : (
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
            )}
            <span>{toast.text}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
