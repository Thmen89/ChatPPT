"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Copy, KeyRound, Trash2 } from "lucide-react";

import LogoutButton from "@/components/Auth/LogoutButton";
import { notify } from "@/components/ui/sonner";
import { ApiToken, authApi, formatWhen } from "./authApi";

const card = "w-full max-w-2xl space-y-4 rounded-[20px] border border-[#EDEEEF] bg-white p-7";
const input =
  "w-full rounded-[11px] border border-[#EDEEEF] bg-white px-4 py-2.5 font-syne text-sm text-black outline-none focus:border-[#a49cfc]";
const primary =
  "inline-flex items-center justify-center gap-2 rounded-[58px] bg-[#7C51F8] px-5 py-2.5 font-syne text-xs font-semibold text-white transition hover:bg-[#6d46e6] disabled:opacity-60";
const secondary =
  "inline-flex items-center justify-center gap-2 rounded-[58px] border border-[#EDEEEF] bg-white px-5 py-2.5 font-syne text-xs font-semibold text-black transition hover:bg-[#F9FAFB] disabled:opacity-60";

/** Your account: password, API tokens (REST and MCP), sign out. */
export default function AccountSettings({ authDisabled }: { authDisabled: boolean }) {
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [tokenName, setTokenName] = useState("");
  const [newToken, setNewToken] = useState<string | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [hasPassword, setHasPassword] = useState(true);

  const load = useCallback(async () => {
    try {
      const [mine, me] = await Promise.all([
        authApi<ApiToken[]>("/tokens"),
        authApi<{ has_password: boolean }>("/me"),
      ]);
      setTokens(mine);
      setHasPassword(me.has_password);
    } catch (error) {
      notify.error("Could not load your account", (error as Error).message);
    }
  }, []);

  useEffect(() => {
    if (!authDisabled) void load();
  }, [authDisabled, load]);

  if (authDisabled) {
    return (
      <div className={card}>
        <h4 className="font-unbounded text-lg font-normal text-black">Account</h4>
        <p className="font-syne text-sm leading-relaxed text-[#494A4D]">
          Sign-in is turned off on this install (<code>auth.disabled</code>), so anyone who can reach it can use it and
          the API needs no token.
        </p>
      </div>
    );
  }

  const createToken = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const created = await authApi<ApiToken & { token: string }>("/tokens", {
        method: "POST",
        body: { name: tokenName.trim() || "API token" },
      });
      setNewToken(created.token);
      setTokenName("");
      await load();
    } catch (error) {
      notify.error("Could not create the token", (error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (token: ApiToken) => {
    try {
      await authApi(`/tokens/${token.id}`, { method: "DELETE" });
      await load();
    } catch (error) {
      notify.error("Could not revoke the token", (error as Error).message);
    }
  };

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await authApi("/password", { method: "POST", body: { current_password: current, new_password: next } });
      setCurrent("");
      setNext("");
      setHasPassword(true);
      notify.success("Password changed", "Your other sessions were signed out.");
    } catch (error) {
      notify.error("Could not change the password", (error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const signOutEverywhere = async () => {
    try {
      await authApi("/logout-all", { method: "POST" });
    } finally {
      window.location.replace("/");
    }
  };

  return (
    <div className="space-y-5">
      <div className={card}>
        <h4 className="font-unbounded text-lg font-normal text-black">API tokens</h4>
        <p className="font-syne text-sm leading-relaxed text-[#494A4D]">
          For scripts and MCP clients: send <code>Authorization: Bearer &lt;token&gt;</code> to <code>/api/v1</code> or{" "}
          <code>/mcp</code>. A token acts as you; revoke it when it is no longer needed.
        </p>
        {newToken ? (
          <div className="space-y-2 rounded-[11px] border border-[#D9D6FE] bg-[#F4F3FF] p-4">
            <p className="font-syne text-xs font-medium text-black">Copy it now; it is not shown again.</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all font-mono text-xs text-black">{newToken}</code>
              <button
                type="button"
                className={secondary}
                onClick={() => {
                  void navigator.clipboard?.writeText(newToken);
                  notify.success("Copied", "The token is on your clipboard.");
                }}
              >
                <Copy className="h-3.5 w-3.5" /> Copy
              </button>
            </div>
          </div>
        ) : null}
        <form onSubmit={createToken} className="flex gap-2">
          <input
            className={input}
            placeholder="Name, e.g. laptop MCP"
            value={tokenName}
            onChange={(e) => setTokenName(e.target.value)}
            maxLength={128}
            aria-label="Token name"
          />
          <button type="submit" disabled={busy} className={primary}>
            <KeyRound className="h-3.5 w-3.5" /> Create
          </button>
        </form>
        {tokens.length ? (
          <ul className="divide-y divide-[#EDEEEF]">
            {tokens.map((token) => (
              <li key={token.id} className="flex items-center justify-between py-2.5 font-syne text-sm">
                <div>
                  <p className="text-black">{token.name}</p>
                  <p className="text-xs text-[#494A4D]">
                    <code>{token.prefix}…</code> · last used {formatWhen(token.last_used_at)}
                  </p>
                </div>
                <button type="button" className={secondary} onClick={() => void revoke(token)} aria-label="Revoke">
                  <Trash2 className="h-3.5 w-3.5" /> Revoke
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="font-syne text-xs text-[#494A4D]">No tokens yet.</p>
        )}
      </div>

      <form onSubmit={changePassword} className={card}>
        <h4 className="font-unbounded text-lg font-normal text-black">Password</h4>
        {hasPassword ? (
          <input
            type="password"
            className={input}
            placeholder="Current password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        ) : (
          <p className="font-syne text-xs text-[#494A4D]">You sign in with single sign-on; a password is optional.</p>
        )}
        <input
          type="password"
          className={input}
          placeholder="New password (at least 8 characters)"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <button type="submit" disabled={busy || next.length < 8} className={primary}>
          Change password
        </button>
      </form>

      <div className={card}>
        <h4 className="font-unbounded text-lg font-normal text-black">Sign out</h4>
        <div className="flex flex-wrap gap-2">
          <LogoutButton label="Sign out" className={primary} />
          <button type="button" className={secondary} onClick={() => void signOutEverywhere()}>
            Sign out everywhere
          </button>
        </div>
      </div>
    </div>
  );
}
