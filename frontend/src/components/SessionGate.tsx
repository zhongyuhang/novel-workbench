import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { openSession, readToken, SESSION_REQUIRED_EVENT } from "../api/client.ts";
import { ApiError } from "../api/types.ts";

type GateState =
  | { kind: "loading" }
  | { kind: "ready" }
  | { kind: "password"; message: string }
  | { kind: "offline"; message: string };

type SessionGateProps = {
  children: ReactNode;
};

export function SessionGate({ children }: SessionGateProps) {
  const [state, setState] = useState<GateState>({ kind: "loading" });
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let active = true;
    const existing = readToken();
    const start = existing ? Promise.resolve() : openSession("");
    start
      .then(() => {
        if (active) {
          setState({ kind: "ready" });
        }
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        setState(gateFromError(error));
      });
    const onSessionRequired = () => {
      setState({ kind: "password", message: "登录状态无效或已过期。" });
    };
    window.addEventListener(SESSION_REQUIRED_EVENT, onSessionRequired);
    return () => {
      active = false;
      window.removeEventListener(SESSION_REQUIRED_EVENT, onSessionRequired);
    };
  }, []);

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    try {
      await openSession(password);
      setState({ kind: "ready" });
    } catch (error: unknown) {
      setState(gateFromError(error));
    } finally {
      setPending(false);
    }
  }

  if (state.kind === "ready") {
    return children;
  }

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <p className="eyebrow">个人长篇</p>
          <p className="wordmark">AI Novel Writer</p>
        </div>
      </header>
      <main className="main">
        <section className="library">
          {state.kind === "loading" ? <p role="status">正在确认登录状态</p> : null}
          {state.kind === "offline" ? (
            <p className="banner banner-error" role="alert">
              {state.message}
            </p>
          ) : null}
          {state.kind === "password" ? (
            <form className="stack-form" onSubmit={submitPassword}>
              <h1>访问口令</h1>
              <p className="hint">
                局域网和生产环境必须先登录。开发环境如果没有设置口令，会直接进入作品库。
              </p>
              <p className="banner banner-error" role="alert">
                {state.message}
              </p>
              <label>
                口令
                <input
                  type="password"
                  value={password}
                  autoComplete="current-password"
                  onChange={(event) => {
                    setPassword(event.target.value);
                  }}
                />
              </label>
              <button className="primary" type="submit" disabled={pending}>
                进入作品库
              </button>
            </form>
          ) : null}
        </section>
      </main>
    </div>
  );
}

function gateFromError(error: unknown): GateState {
  if (error instanceof ApiError) {
    if (error.code === "PASSWORD_REQUIRED" || error.code === "INVALID_PASSWORD") {
      return { kind: "password", message: error.message };
    }
    if (error.code === "NETWORK") {
      return { kind: "offline", message: error.message };
    }
  }
  return { kind: "offline", message: "无法建立本机会话。" };
}
