export function isTruthyAuthValue(value?: string | null): boolean {
  const raw = value?.trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

export function getDisableAuthValue(): string | undefined {
  if (typeof window !== "undefined" && window.env?.DISABLE_AUTH) {
    return window.env.DISABLE_AUTH;
  }

  if (typeof process !== "undefined") {
    // CHATPPT_AUTH__DISABLED is the chatppt.toml key's env form (auth.disabled).
    return process.env.DISABLE_AUTH || process.env.CHATPPT_AUTH__DISABLED;
  }

  return undefined;
}

export function isAuthDisabled(): boolean {
  return isTruthyAuthValue(getDisableAuthValue());
}
