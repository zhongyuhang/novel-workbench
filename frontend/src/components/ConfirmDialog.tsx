import { useEffect, useRef, useState } from "react";

type ConfirmTone = "default" | "danger";

type ConfirmRequest = {
  message: string;
  tone: ConfirmTone;
  resolve: (value: boolean) => void;
};

let enqueue: ((request: ConfirmRequest) => void) | null = null;

export function confirmDialog(message: string, options?: { tone?: ConfirmTone }): Promise<boolean> {
  if (!enqueue) {
    return Promise.resolve(window.confirm(message));
  }
  return new Promise((resolve) => {
    enqueue?.({
      message,
      tone: options?.tone ?? "default",
      resolve,
    });
  });
}

export function ConfirmHost() {
  const [current, setCurrent] = useState<ConfirmRequest | null>(null);
  const currentRef = useRef<ConfirmRequest | null>(null);
  const queue = useRef<ConfirmRequest[]>([]);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    enqueue = (request) => {
      if (currentRef.current) {
        queue.current.push(request);
        return;
      }
      currentRef.current = request;
      setCurrent(request);
    };
    return () => {
      enqueue = null;
      const leftover = [currentRef.current, ...queue.current].filter((item) => item !== null);
      currentRef.current = null;
      queue.current = [];
      for (const request of leftover) {
        request.resolve(window.confirm(request.message));
      }
    };
  }, []);

  useEffect(() => {
    const node = dialogRef.current;
    if (!node) {
      return;
    }
    if (current && !node.open) {
      node.showModal();
    }
    if (!current && node.open) {
      node.close();
    }
  }, [current]);

  function settle(value: boolean) {
    const active = currentRef.current;
    if (!active) {
      return;
    }
    active.resolve(value);
    const next = queue.current.shift() ?? null;
    currentRef.current = next;
    setCurrent(next);
  }

  return (
    <dialog
      ref={dialogRef}
      className="confirm-dialog"
      aria-labelledby="confirm-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        settle(false);
      }}
      onClick={(event) => {
        if (event.target === dialogRef.current) {
          settle(false);
        }
      }}
    >
      <h2 id="confirm-dialog-title">请确认</h2>
      <p>{current?.message}</p>
      <div className="dialog-actions">
        <button className="ghost" type="button" onClick={() => settle(false)}>
          取消
        </button>
        <button
          className={current?.tone === "danger" ? "danger-fill" : "primary"}
          type="button"
          onClick={() => settle(true)}
        >
          确定
        </button>
      </div>
    </dialog>
  );
}
