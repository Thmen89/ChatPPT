"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Trash2, UserPlus } from "lucide-react";

import { notify } from "@/components/ui/sonner";
import { AccountUser, ApiToken, authApi, formatWhen } from "./authApi";

const card = "w-full max-w-3xl space-y-3 border-b border-zinc-200 pb-6";
const input =
  "h-8 rounded-md border border-zinc-200 bg-white px-2.5 text-[13px] text-zinc-900 outline-none focus:border-zinc-400";
const primary =
  "inline-flex h-8 items-center justify-center gap-2 rounded-md bg-zinc-900 px-3 text-[13px] font-medium text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-60";
const small =
  "rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-700 hover:bg-zinc-50";

/** Admins: add people, make admins, disable, reset passwords, revoke anyone's tokens. */
export default function UsersAdmin({ currentUser }: { currentUser: string | null }) {
  const [users, setUsers] = useState<AccountUser[]>([]);
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  const load = useCallback(async () => {
    try {
      const [all, allTokens] = await Promise.all([
        authApi<AccountUser[]>("/users"),
        authApi<ApiToken[]>("/tokens/all"),
      ]);
      setUsers(all);
      setTokens(allTokens);
    } catch (error) {
      notify.error("Could not load users", (error as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (action: () => Promise<unknown>, failure: string) => {
    try {
      await action();
      await load();
    } catch (error) {
      notify.error(failure, (error as Error).message);
    }
  };

  const add = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await authApi("/users", { method: "POST", body: { username, password, is_admin: isAdmin } });
      setUsername("");
      setPassword("");
      setIsAdmin(false);
    }, "Could not add the user");
  };

  const resetPassword = (user: AccountUser) => {
    const value = window.prompt(`New password for ${user.username} (at least 8 characters)`);
    if (!value) return;
    void run(
      () => authApi(`/users/${user.id}`, { method: "PATCH", body: { password: value } }),
      "Could not reset the password"
    );
  };

  return (
    <div className="space-y-5">
      <div className={card}>
        <h4 className="text-sm font-semibold text-zinc-900">Users</h4>
        <p className="text-sm text-zinc-500">
          Everyone shares the same decks and templates. Only admins change provider keys, settings and users.
        </p>
        <form onSubmit={add} className="flex flex-wrap items-center gap-2">
          <input
            className={input}
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            aria-label="Username"
          />
          <input
            className={input}
            type="password"
            placeholder="Password (8+ characters)"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-label="Password"
          />
          <label className="flex items-center gap-1.5 text-xs text-zinc-900">
            <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} /> Admin
          </label>
          <button type="submit" className={primary} disabled={!username.trim() || password.length < 8}>
            <UserPlus className="h-3.5 w-3.5" /> Add
          </button>
        </form>
        <ul className="divide-y divide-zinc-100">
          {users.map((user) => (
            <li key={user.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
              <div>
                <p className={user.is_active ? "text-zinc-900" : "text-zinc-400 line-through"}>
                  {user.username}
                  {user.is_admin ? <span className="ml-2 text-[10px] text-zinc-500">ADMIN</span> : null}
                  {user.source !== "local" ? (
                    <span className="ml-2 text-[10px] text-zinc-500">{user.source.toUpperCase()}</span>
                  ) : null}
                </p>
                <p className="text-xs text-zinc-500">last sign-in {formatWhen(user.last_login_at)}</p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  className={small}
                  onClick={() =>
                    void run(
                      () => authApi(`/users/${user.id}`, { method: "PATCH", body: { is_admin: !user.is_admin } }),
                      "Could not change the role"
                    )
                  }
                >
                  {user.is_admin ? "Remove admin" : "Make admin"}
                </button>
                <button type="button" className={small} onClick={() => resetPassword(user)}>
                  Reset password
                </button>
                <button
                  type="button"
                  className={small}
                  onClick={() =>
                    void run(
                      () => authApi(`/users/${user.id}`, { method: "PATCH", body: { is_active: !user.is_active } }),
                      "Could not change the user"
                    )
                  }
                >
                  {user.is_active ? "Disable" : "Enable"}
                </button>
                {user.username !== currentUser ? (
                  <button
                    type="button"
                    className={small}
                    aria-label={`Delete ${user.username}`}
                    onClick={() => {
                      if (window.confirm(`Delete ${user.username} and their API tokens?`)) {
                        void run(() => authApi(`/users/${user.id}`, { method: "DELETE" }), "Could not delete the user");
                      }
                    }}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className={card}>
        <h4 className="text-sm font-semibold text-zinc-900">All API tokens</h4>
        {tokens.length ? (
          <ul className="divide-y divide-zinc-100">
            {tokens.map((token) => (
              <li key={token.id} className="flex items-center justify-between py-2.5 text-sm">
                <p className="text-zinc-900">
                  {token.username} · {token.name}{" "}
                  <span className="text-xs text-zinc-500">
                    <code>{token.prefix}…</code> · last used {formatWhen(token.last_used_at)}
                  </span>
                </p>
                <button
                  type="button"
                  className={small}
                  onClick={() =>
                    void run(() => authApi(`/tokens/${token.id}`, { method: "DELETE" }), "Could not revoke the token")
                  }
                >
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-zinc-500">No API tokens.</p>
        )}
      </div>
    </div>
  );
}
