import { NextRequest, NextResponse } from "next/server";

// Same-origin proxy to the gateway, so the browser needs no CORS and never learns more than these
// read-only views and the review decision. Anything else is refused.
const GATEWAY_URL = (process.env.GATEWAY_URL ?? "http://127.0.0.1:8787").replace(/\/$/, "");

const READ = /^(ledger\/summary|ledger\/requests|ledger\/requests\/\d+|ledger\/sessions|status|review)$/;
const DECIDE = /^review\/\d+$/;

type Ctx = { params: Promise<{ path: string[] }> };

async function forward(req: NextRequest, ctx: Ctx, allowed: RegExp, method: "GET" | "POST") {
  const sub = (await ctx.params).path.join("/");
  if (!allowed.test(sub)) {
    return NextResponse.json({ error: "not proxied" }, { status: 404 });
  }
  const url = `${GATEWAY_URL}/v1/${sub}${req.nextUrl.search}`;
  try {
    const res = await fetch(url, {
      method,
      cache: "no-store",
      headers: method === "POST" ? { "content-type": "application/json" } : undefined,
      body: method === "POST" ? await req.text() : undefined,
    });
    const body = await res.text();
    return new NextResponse(body, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return NextResponse.json({ error: "gateway unreachable", gateway: GATEWAY_URL }, { status: 502 });
  }
}

export async function GET(req: NextRequest, ctx: Ctx) {
  return forward(req, ctx, READ, "GET");
}

export async function POST(req: NextRequest, ctx: Ctx) {
  return forward(req, ctx, DECIDE, "POST");
}
