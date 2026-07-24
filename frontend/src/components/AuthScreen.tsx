import { FormEvent, useState } from "react";
import { LockKeyhole, Map } from "lucide-react";
import { api } from "../lib/api";

interface Props {
  setupRequired: boolean;
  onAuthenticated: () => void;
}

export function AuthScreen({ setupRequired, onAuthenticated }: Props) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (setupRequired && password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (setupRequired) await api.setup(username, password);
      else await api.login(username, password);
      onAuthenticated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <div className="brand-mark large">
          <Map size={23} strokeWidth={1.7} />
        </div>
        <p className="eyebrow">LOCAL WORKSTATION</p>
        <h1>{setupRequired ? "Secure your mapper" : "Welcome back"}</h1>
        <p className="auth-copy">
          {setupRequired
            ? "Create the one local administrator. Registration closes permanently after this step."
            : "Sign in to your private aerial processing workstation."}
        </p>
        <form onSubmit={submit}>
          <label>
            Username
            <input
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete={setupRequired ? "new-password" : "current-password"}
              minLength={12}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {setupRequired && (
            <label>
              Confirm password
              <input
                type="password"
                autoComplete="new-password"
                minLength={12}
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
              />
            </label>
          )}
          {error && <div className="form-error">{error}</div>}
          <button className="button primary auth-button" disabled={busy}>
            <LockKeyhole size={15} />
            {busy ? "Please wait…" : setupRequired ? "Create administrator" : "Sign in"}
          </button>
        </form>
        <p className="auth-footnote">Bound locally · Private through Tailscale · AGPLv3</p>
      </section>
    </main>
  );
}
