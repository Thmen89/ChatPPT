import { NextRequest, NextResponse } from 'next/server';

import { isAuthDisabled } from '@/utils/auth';

export const dynamic = 'force-dynamic';

const canChangeKeys = process.env.CAN_CHANGE_KEYS !== "false";

function fastApiBaseUrl(): string {
  const url =
    process.env.FAST_API_INTERNAL_URL?.trim() || process.env.NEXT_PUBLIC_FAST_API?.trim() || "http://127.0.0.1:8000";
  return url.replace(/\/+$/, "");
}

/** Provider keys and settings are for admins: everyone else gets the locked view
 * (the same one CAN_CHANGE_KEYS=false gives). */
async function isAdmin(request: NextRequest): Promise<boolean> {
  if (isAuthDisabled()) return true;
  const cookie = request.headers.get("cookie");
  if (!cookie) return false;
  try {
    const response = await fetch(`${fastApiBaseUrl()}/api/v1/auth/status`, {
      headers: { cookie },
      cache: "no-store",
    });
    if (!response.ok) return false;
    const status = (await response.json()) as { is_admin?: boolean };
    return Boolean(status.is_admin);
  } catch {
    return false;
  }
}

export async function GET(request: NextRequest) {
  return NextResponse.json({ canChange: canChangeKeys && (await isAdmin(request)) })
}
