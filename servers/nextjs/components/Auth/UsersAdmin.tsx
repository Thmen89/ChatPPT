"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Trash2, UserPlus } from "lucide-react";

import { notify } from "@/components/ui/sonner";
import { AccountUser, ApiToken, authApi, formatWhen } from "./authApi";

const card = "w-full max-w-3xl space-y-4 rounded-[20px] border border-[#EDEEEF] bg-white p-7";
const input =
  "rounded-[11px] border border-[#EDEEEF] bg-white px-4 py-2.5 font-syne text-sm text-black outline-none focus:border-[#a49cfc]";
const primary =
  "inline-flex items-center justify-center gap-2 rounded-[58px] bg-[#7C51F8] px-5 py-2.5 font-syne text-xs font-semibold text-white transition hover:bg-[#6d46e6] disabled:opacity-60";
const small =
  "rounded-[58px] border border-[#EDEEEF] bg-white px-3 py-1.5 font-syne text-[11px] font-medium text-black transition hover:bg-[#F9FAFB]";

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
        <h4 className="font-unbounded text-lg font-normal text-black">Users</h4>
        <p className="font-syne text-sm text-[#494A4D]">
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
          <label className="flex items-center gap-1.5 font-syne text-xs text-black">
            <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} /> Admin
          </label>
          <button type="submit" className={primary} disabled={!username.trim() || password.length < 8}>
            <UserPlus className="h-3.5 w-3.5" /> Add
          </button>
        </form>
        <ul className="divide-y divide-[#EDEEEF]">
          {users.map((user) => (
            <li key={user.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 font-syne text-sm">
              <div>
                <p className={user.is_active ? "text-black" : "text-[#999999] line-through"}>
                  {user.username}
                  {user.is_admin ? <span className="ml-2 text-[10px] text-[#7A5AF8]">ADMIN</span> : null}
                  {user.source !== "local" ? (
                    <span className="ml-2 text-[10px] text-[#494A4D]">{user.source.toUpperCase()}</span>
                  ) : null}
                </p>
                <p className="text-xs text-[#494A4D]">last sign-in {formatWhen(user.last_login_at)}</p>
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
        <h4 className="font-unbounded text-lg font-normal text-black">All API tokens</h4>
        {tokens.length ? (
          <ul className="divide-y divide-[#EDEEEF]">
            {tokens.map((token) => (
              <li key={token.id} className="flex items-center justify-between py-2.5 font-syne text-sm">
                <p className="text-black">
                  {token.username} · {token.name}{" "}
                  <span className="text-xs text-[#494A4D]">
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
          <p className="font-syne text-xs text-[#494A4D]">No API tokens.</p>
        )}
      </div>
    </div>
  );
}
