import { NextResponse } from 'next/server';

/** Process-only liveness: no database or backend dependency work. */
export function GET() {
  return NextResponse.json(
    { status: 'ok' },
    { headers: { 'Cache-Control': 'no-store, max-age=0' } },
  );
}
